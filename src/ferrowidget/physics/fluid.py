"""240 Hz semi-implicit Euler physics simulation for 64 ferrofluid droplets and 19 electromagnets."""

from __future__ import annotations

import math

import numpy as np

from ferrowidget.audio.analysis import Features


class FluidSimulation:
    """Zero-heap-churn 2D metaball physics engine with underdamped spring choreography."""

    def __init__(self, seed: int = 42, preset: str = "club"):
        self.rng = np.random.Generator(np.random.PCG64(seed))
        self.dt = 1.0 / 240.0
        self.time = 0.0
        self.accumulated_dt = 0.0

        # Presets configuration
        self.preset = preset
        self.viscosity = 1.0
        self.magnet_gain = 1.0
        self.kick_impulse = 1.0
        self.spike_amount = 1.0
        self.idle_breathing = True
        self._apply_preset_params(preset)

        # Droplet hierarchy: 64 droplets total
        # 6 core blobs (r0: 0.13..0.24, weight: 1.0)
        # 22 satellite blobs (r0: 0.045..0.085, weight: 0.85)
        # 36 mist droplets (r0: 0.015..0.030, weight: 0.65)
        self.n_blobs = 64
        self.n_core = 6
        self.n_sat = 22
        self.n_mist = 36

        # Allocate simulation arrays
        self.pos = np.zeros((self.n_blobs, 2), dtype=np.float32)
        self.vel = np.zeros((self.n_blobs, 2), dtype=np.float32)
        self.forces = np.zeros((self.n_blobs, 2), dtype=np.float32)
        self.weights = np.ones(self.n_blobs, dtype=np.float32)

        self.r0 = np.zeros(self.n_blobs, dtype=np.float32)
        self.r = np.zeros(self.n_blobs, dtype=np.float32)
        self.r_vel = np.zeros(self.n_blobs, dtype=np.float32)
        self.r_target = np.zeros(self.n_blobs, dtype=np.float32)

        # Spring constants for radii (zeta = 0.55, omega = 18.0 rad/s)
        self.r_zeta = 0.55
        self.r_omega = 18.0

        # Global Rosensweig spike amount spring (zeta = 0.45, omega = 24.0 rad/s)
        self.spike = 0.0
        self.spike_vel = 0.0
        self.spike_target = 0.0
        self.spike_zeta = 0.45
        self.spike_omega = 24.0

        # 19 Electromagnets:
        # 0: center (0, 0)
        # 1..6: inner ring radius 0.30
        # 7..18: outer ring radius 0.62
        self.n_magnets = 19
        self.magnet_pos = np.zeros((self.n_magnets, 2), dtype=np.float32)
        self.magnet_str = np.zeros(self.n_magnets, dtype=np.float32)
        self._init_magnet_positions()

        # Preallocated uniform data arrays for zero heap churn
        self._blobs_uniform = np.zeros((self.n_blobs, 4), dtype=np.float32)
        self._magnets_uniform = np.zeros((self.n_magnets, 4), dtype=np.float32)
        self._magnets_uniform[:, 0:2] = self.magnet_pos

        # Pairwise interaction preallocated mask
        self._not_diagonal = ~np.eye(self.n_blobs, dtype=bool)

        # Audio impulse edge tracking
        self.prev_kick = 0.0
        self.prev_snare = 0.0
        self.prev_hat = 0.0

        # Boundary confinement
        self.boundary_r = 0.92

        # Initialize droplet hierarchy
        self._init_droplets()

    def _apply_preset_params(self, preset: str) -> None:
        self.preset = preset
        if preset == "calm":
            self.viscosity = 1.35
            self.magnet_gain = 0.55
            self.kick_impulse = 0.65
            self.spike_amount = 0.20
        elif preset == "cinematic":
            self.viscosity = 1.20
            self.magnet_gain = 0.90
            self.kick_impulse = 1.10
            self.spike_amount = 0.45
        else:  # "club"
            self.viscosity = 1.00
            self.magnet_gain = 0.70
            self.kick_impulse = 0.95
            self.spike_amount = 0.35

    def _init_magnet_positions(self) -> None:
        self.magnet_pos[0] = [0.0, 0.0]

        # Inner ring: 6 magnets at r = 0.30
        r_inner = 0.30
        for i in range(6):
            angle = (2.0 * math.pi * i) / 6.0
            self.magnet_pos[1 + i] = [r_inner * math.cos(angle), r_inner * math.sin(angle)]

        # Outer ring: 12 magnets at r = 0.62
        r_outer = 0.62
        for i in range(12):
            angle = (2.0 * math.pi * i) / 12.0
            self.magnet_pos[7 + i] = [r_outer * math.cos(angle), r_outer * math.sin(angle)]

    def _init_droplets(self) -> None:
        # 6 core blobs
        for i in range(self.n_core):
            r_val = float(self.rng.uniform(0.13, 0.24))
            self.r0[i] = r_val
            self.r[i] = r_val
            self.r_target[i] = r_val
            self.weights[i] = 1.0
            angle = float(self.rng.uniform(0, 2 * math.pi))
            dist = float(self.rng.uniform(0.02, 0.22))
            self.pos[i] = [dist * math.cos(angle), dist * math.sin(angle)]

        # 22 satellite blobs
        for i in range(self.n_core, self.n_core + self.n_sat):
            r_val = float(self.rng.uniform(0.045, 0.085))
            self.r0[i] = r_val
            self.r[i] = r_val
            self.r_target[i] = r_val
            self.weights[i] = 0.85
            angle = float(self.rng.uniform(0, 2 * math.pi))
            dist = float(self.rng.uniform(0.25, 0.65))
            self.pos[i] = [dist * math.cos(angle), dist * math.sin(angle)]

        # 36 mist droplets
        for i in range(self.n_core + self.n_sat, self.n_blobs):
            r_val = float(self.rng.uniform(0.015, 0.030))
            self.r0[i] = r_val
            self.r[i] = r_val
            self.r_target[i] = r_val
            self.weights[i] = 0.65
            angle = float(self.rng.uniform(0, 2 * math.pi))
            dist = float(self.rng.uniform(0.35, 0.85))
            self.pos[i] = [dist * math.cos(angle), dist * math.sin(angle)]

    def update_choreography(self, feat: Features, delta_seconds: float) -> None:
        """Run fixed 240 Hz substeps for frame delta time (clamped to 0.1s max)."""
        clamped_dt = min(delta_seconds, 0.10)
        self.accumulated_dt += clamped_dt

        # Check for impulse triggers on positive edges
        kick_jump = max(0.0, feat.kick - self.prev_kick)
        snare_jump = max(0.0, feat.snare - self.prev_snare)
        hat_jump = max(0.0, feat.hat - self.prev_hat)
        self.prev_kick = feat.kick
        self.prev_snare = feat.snare
        self.prev_hat = feat.hat

        # Update magnets based on audio bands
        # Center magnet: gentle so it does not collapse separate droplets into one solid ball
        self.magnet_str[0] = (0.22 * feat.sub + 0.18 * feat.kick) * self.magnet_gain

        # Continuous rotation of outer ring sector mapping: 2*pi / 90.0 rad/s
        rot_angle = (2.0 * math.pi / 90.0) * self.time

        # Inner ring: lowmid and mid
        for i in range(6):
            val = (0.35 * feat.lowmid + 0.25 * feat.mid) * (1.0 + 0.25 * math.sin(rot_angle + i))
            self.magnet_str[1 + i] = val * self.magnet_gain

        # Outer ring: 32 bands folded into 12 sectors
        for i in range(12):
            band_idx = int((i / 12.0) * len(feat.bands)) % len(feat.bands)
            val = (
                feat.bands[band_idx] * 0.40
                + 0.20 * feat.highmid
                + 0.15 * feat.air
                + 0.25 * feat.hat
            )
            # Stereo balance bias
            x_m = self.magnet_pos[7 + i, 0]
            bias = 1.0 + 0.35 * feat.balance * (1.0 if x_m >= 0 else -1.0)
            self.magnet_str[7 + i] = val * bias * self.magnet_gain

        # Underdamped target radius for each droplet with organic idle breathing
        idle_breath = 0.06 * math.sin(2.5 * self.time)
        for i in range(self.n_blobs):
            band_val = feat.bands[i % len(feat.bands)]
            self.r_target[i] = self.r0[i] * (1.0 + 0.25 * band_val + 0.35 * feat.bass + idle_breath)

        # Global Rosensweig spike target (soft, organic fluid crests)
        spike_target_val = (
            min(1.0, 0.45 * feat.bass + 0.55 * feat.sub + 0.45 * feat.kick) * self.spike_amount
        )
        self.spike_target = spike_target_val

        # Substep integration
        while self.accumulated_dt >= self.dt:
            self._substep(feat, kick_jump, snare_jump, hat_jump)
            kick_jump = 0.0
            snare_jump = 0.0
            hat_jump = 0.0
            self.accumulated_dt -= self.dt
            self.time += self.dt

    def _substep(
        self,
        feat: Features,
        kick_jump: float,
        snare_jump: float,
        hat_jump: float,
    ) -> None:
        """Single 240 Hz semi-implicit Euler integration step with zero heap churn."""
        dt = self.dt
        self.forces.fill(0.0)

        # 1. Update underdamped spring ODEs
        # Radii springs: x'' + 2*zeta*omega*x' + omega^2*(x - x_target) = 0
        r_acc = -2.0 * self.r_zeta * self.r_omega * self.r_vel - (self.r_omega**2) * (self.r - self.r_target)
        self.r_vel += r_acc * dt
        self.r += self.r_vel * dt
        np.clip(self.r, 0.01, 0.40, out=self.r)

        # Spike amount spring: zeta = 0.45, omega = 24.0 rad/s
        spike_acc = (
            -2.0 * self.spike_zeta * self.spike_omega * self.spike_vel
            - (self.spike_omega**2) * (self.spike - self.spike_target)
        )
        self.spike_vel += spike_acc * dt
        self.spike += self.spike_vel * dt
        self.spike = max(0.0, min(2.0, self.spike))

        # 2. Audio Impulses
        # Kick: strong radial outward impulse + tangential scatter
        if kick_jump > 0.15:
            imp_strength = kick_jump * 1.8 * self.kick_impulse
            p = self.pos[:self.n_core + self.n_sat]
            d = np.sqrt(p[:, 0]**2 + p[:, 1]**2)[:, None] + 1e-4
            radial = p / d
            tangent_x = -radial[:, 1]
            tangent_y = radial[:, 0]
            scatter = self.rng.uniform(-0.3, 0.3, size=len(p)).astype(np.float32)
            self.vel[:self.n_core + self.n_sat, 0] += (radial[:, 0] + scatter * tangent_x) * imp_strength
            self.vel[:self.n_core + self.n_sat, 1] += (radial[:, 1] + scatter * tangent_y) * imp_strength

        # Snare: vortex swirl
        if snare_jump > 0.15:
            swirl_strength = snare_jump * 1.2
            d = np.sqrt(self.pos[:, 0]**2 + self.pos[:, 1]**2) + 1e-4
            self.vel[:, 0] += (-self.pos[:, 1] / d) * swirl_strength
            self.vel[:, 1] += (self.pos[:, 0] / d) * swirl_strength

        # Hat: micro-impulses to mist droplets
        if hat_jump > 0.15:
            mist_imp = hat_jump * 0.9
            mist_slice = slice(self.n_core + self.n_sat, self.n_blobs)
            self.vel[mist_slice] += self.rng.uniform(-mist_imp, mist_imp, size=(self.n_mist, 2)).astype(np.float32)

        # 3. Magnetic Attraction: Vectorized across all 19 magnets
        eps2 = 0.08**2
        G = 4.2
        dx_m = self.magnet_pos[None, :, 0] - self.pos[:, None, 0]  # (64, 19)
        dy_m = self.magnet_pos[None, :, 1] - self.pos[:, None, 1]  # (64, 19)
        dist2_m = dx_m * dx_m + dy_m * dy_m
        denom_m = np.power(dist2_m + eps2, 1.25)

        fm_x = G * (self.magnet_str[None, :] * dx_m) / denom_m
        fm_y = G * (self.magnet_str[None, :] * dy_m) / denom_m

        # Clamp individual magnet force magnitudes
        flen = np.sqrt(fm_x * fm_x + fm_y * fm_y) + 1e-5
        scale_m = np.minimum(1.0, 15.0 / flen)
        self.forces[:, 0] += np.sum(fm_x * scale_m, axis=1)
        self.forces[:, 1] += np.sum(fm_y * scale_m, axis=1)

        # 4. Pairwise droplet interactions: Cohesion + Repulsion across all droplets
        # Fast 2D broadcasting
        dx = self.pos[:, 0:1].T - self.pos[:, 0:1]  # dx[i, j] = pos[j] - pos[i]
        dy = self.pos[:, 1:2].T - self.pos[:, 1:2]
        d2 = dx * dx + dy * dy
        dist = np.sqrt(d2) + 1e-5
        inv_d = 1.0 / dist
        dir_x = dx * inv_d
        dir_y = dy * inv_d

        sum_r = self.r[:, None] + self.r[None, :]

        # Soft cohesion: 1.10 * sum_r < d < 2.5 * sum_r
        coh_m = (dist > 1.10 * sum_r) & (dist < 2.5 * sum_r)
        f_coh = np.where(coh_m, 1.5 * ((dist - 1.10 * sum_r) / sum_r), 0.0)

        # Core repulsion: keep droplets separate and organic, preventing a uniform ball
        rep_m = (dist < 0.70 * sum_r) & self._not_diagonal
        f_rep = np.where(rep_m, 5.0 * ((0.70 * sum_r - dist) / sum_r), 0.0)

        f_net = f_coh - f_rep
        self.forces[:, 0] += np.sum(f_net * dir_x, axis=1)
        self.forces[:, 1] += np.sum(f_net * dir_y, axis=1)

        # 5. Continuous swirling vortex + Curl-noise drift
        # Keeps the organic swirling orbit active at all times, accelerating with music
        d_origin = np.sqrt(self.pos[:, 0]**2 + self.pos[:, 1]**2) + 1e-4
        tangent_x = -self.pos[:, 1] / d_origin
        tangent_y = self.pos[:, 0] / d_origin
        swirl_torque = 0.50 + 0.90 * feat.loudness + 1.20 * feat.snare
        self.forces[:, 0] += tangent_x * swirl_torque
        self.forces[:, 1] += tangent_y * swirl_torque

        curl_scale = 0.35 * (1.0 + 0.60 * feat.loudness + 0.40 * feat.excitement)
        px = self.pos[:, 0]
        py = self.pos[:, 1]
        curl_x = -2.0 * np.pi * np.sin(2.0 * np.pi * px) * np.sin(2.0 * np.pi * py) + np.pi * np.cos(4.0 * np.pi * py)
        curl_y = -2.0 * np.pi * np.cos(2.0 * np.pi * px) * np.cos(2.0 * np.pi * py)
        self.forces[:, 0] += curl_x * curl_scale
        self.forces[:, 1] += curl_y * curl_scale

        # 6. Viscous drag: -c_drag * v
        c_drag = 2.4 * self.viscosity
        self.forces -= c_drag * self.vel

        # 7. Semi-implicit Euler integration
        self.vel += (self.forces / self.weights[:, None]) * dt
        # Velocity cap for numerical stability
        v_sq = self.vel[:, 0]**2 + self.vel[:, 1]**2
        v_norm = np.sqrt(v_sq)[:, None] + 1e-5
        v_scale = np.minimum(1.0, 6.0 / v_norm)
        self.vel *= v_scale

        self.pos += self.vel * dt

        # 8. Boundary wall confinement (radius 0.92) - Vectorized
        pos_dist = np.sqrt(self.pos[:, 0]**2 + self.pos[:, 1]**2)
        wall_mask = pos_dist > self.boundary_r
        if np.any(wall_mask):
            inv_pdist = 1.0 / np.maximum(pos_dist, 1e-5)
            norm_x = self.pos[:, 0] * inv_pdist
            norm_y = self.pos[:, 1] * inv_pdist
            penetration = np.maximum(0.0, pos_dist - self.boundary_r)

            self.pos[:, 0] -= norm_x * penetration
            self.pos[:, 1] -= norm_y * penetration

            v_dot_n = self.vel[:, 0] * norm_x + self.vel[:, 1] * norm_y
            reflect_mask = wall_mask & (v_dot_n > 0.0)
            self.vel[:, 0] -= np.where(reflect_mask, 1.20 * v_dot_n * norm_x, 0.0)
            self.vel[:, 1] -= np.where(reflect_mask, 1.20 * v_dot_n * norm_y, 0.0)

    def get_blobs_uniform_data(self) -> np.ndarray:
        """Return preallocated float32 array of shape (64, 4) for GLSL uBlobs: vec4(x, y, r, weight)."""
        self._blobs_uniform[:, 0:2] = self.pos
        self._blobs_uniform[:, 2] = self.r
        self._blobs_uniform[:, 3] = self.weights
        return self._blobs_uniform

    def get_magnets_uniform_data(self) -> np.ndarray:
        """Return preallocated float32 array of shape (19, 4) for GLSL uMagnets: vec4(x, y, strength, 0)."""
        self._magnets_uniform[:, 2] = self.magnet_str
        return self._magnets_uniform
