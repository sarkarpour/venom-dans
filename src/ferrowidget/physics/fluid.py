"""240 Hz semi-implicit Euler physics simulation for 64 ferrofluid droplets and 19 electromagnets."""

from __future__ import annotations

import math

import numpy as np

from ferrowidget.audio.analysis import Features


class FluidSimulation:
    """Preallocated 2D metaball physics engine with underdamped spring choreography."""

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
            self.viscosity = 1.45
            self.magnet_gain = 0.75
            self.kick_impulse = 0.65
            self.spike_amount = 0.50
        elif preset == "cinematic":
            self.viscosity = 1.30
            self.magnet_gain = 1.25
            self.kick_impulse = 1.15
            self.spike_amount = 1.40
        else:  # "club"
            self.viscosity = 1.00
            self.magnet_gain = 1.00
            self.kick_impulse = 1.00
            self.spike_amount = 1.00

    def _init_magnet_positions(self) -> None:
        # Center magnet
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
            # Cluster near center
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
        # Center magnet: driven by 0.65 * sub + 0.55 * kick
        self.magnet_str[0] = (0.65 * feat.sub + 0.55 * feat.kick) * self.magnet_gain

        # Continuous rotation of outer ring sector mapping: 2*pi / 90.0 rad/s
        rot_angle = (2.0 * math.pi / 90.0) * self.time

        # Inner ring: lowmid and mid
        for i in range(6):
            val = (0.6 * feat.lowmid + 0.4 * feat.mid) * (1.0 + 0.25 * math.sin(rot_angle + i))
            self.magnet_str[1 + i] = val * self.magnet_gain

        # Outer ring: 32 bands folded into 12 sectors, boosted by highmid, air, hat
        for i in range(12):
            band_idx = int((i / 12.0) * len(feat.bands)) % len(feat.bands)
            val = (
                feat.bands[band_idx] * 0.7
                + 0.3 * feat.highmid
                + 0.2 * feat.air
                + 0.4 * feat.hat
            )
            # Stereo balance bias
            x_m = self.magnet_pos[7 + i, 0]
            bias = 1.0 + 0.35 * feat.balance * (1.0 if x_m >= 0 else -1.0)
            self.magnet_str[7 + i] = val * bias * self.magnet_gain

        # Underdamped target radius for each droplet
        # Idle breathing oscillation
        idle_breath = 0.05 * math.sin(2.0 * self.time) if (feat.is_silent or self.idle_breathing) else 0.0
        for i in range(self.n_blobs):
            band_val = feat.bands[i % len(feat.bands)]
            self.r_target[i] = self.r0[i] * (1.0 + 0.35 * band_val + 0.55 * feat.bass + idle_breath)

        # Global Rosensweig spike target
        spike_target_val = (
            min(1.0, 0.75 * feat.bass + 0.95 * feat.sub + 0.85 * feat.kick) * self.spike_amount
        )
        self.spike_target = spike_target_val

        # Substep integration
        while self.accumulated_dt >= self.dt:
            self._substep(feat, kick_jump, snare_jump, hat_jump)
            # Only apply edge impulses once
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
        """Single 240 Hz semi-implicit Euler integration step."""
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
        # Kick: strong radial expansion + tangential scatter
        if kick_jump > 0.15:
            imp_strength = kick_jump * 1.8 * self.kick_impulse
            for i in range(self.n_core + self.n_sat):
                p = self.pos[i]
                d = float(np.linalg.norm(p)) + 1e-4
                radial = p / d
                tangent = np.array([-radial[1], radial[0]], dtype=np.float32)
                scatter = 0.3 * (self.rng.uniform(-1.0, 1.0))
                self.vel[i] += (radial + scatter * tangent) * imp_strength

        # Snare: vortex swirl
        if snare_jump > 0.15:
            swirl_strength = snare_jump * 1.2
            for i in range(self.n_blobs):
                p = self.pos[i]
                d = float(np.linalg.norm(p)) + 1e-4
                tangent = np.array([-p[1], p[0]], dtype=np.float32) / d
                self.vel[i] += tangent * swirl_strength

        # Hat: micro-impulses to mist
        if hat_jump > 0.15:
            mist_imp = hat_jump * 0.9
            for i in range(self.n_core + self.n_sat, self.n_blobs):
                self.vel[i] += self.rng.uniform(-mist_imp, mist_imp, size=2).astype(np.float32)

        # 3. Magnetic Attraction: Vectorized across all 19 magnets
        eps2 = 0.08**2
        G = 4.2
        delta_m = self.magnet_pos[None, :, :] - self.pos[:, None, :]
        dist2_m = np.sum(delta_m * delta_m, axis=2, keepdims=True)
        denom_m = np.power(dist2_m + eps2, 1.25)
        mag_forces_all = G * (self.magnet_str[None, :, None] * delta_m) / denom_m
        f_len_m = np.linalg.norm(mag_forces_all, axis=2, keepdims=True) + 1e-5
        scale_m = np.minimum(1.0, 15.0 / f_len_m)
        self.forces += np.sum(mag_forces_all * scale_m, axis=1)

        # 4. Pairwise droplet interactions: Cohesion + Core Repulsion (Vectorized)
        n_int = self.n_core + self.n_sat
        p_int = self.pos[:n_int]
        r_int = self.r[:n_int]

        diff = p_int[None, :, :] - p_int[:, None, :]  # shape (28, 28, 2): p_j - p_i
        dist = np.linalg.norm(diff, axis=2, keepdims=True) + 1e-5
        dir_ij = diff / dist

        sum_r = (r_int[:, None] + r_int[None, :])[:, :, None]

        # Soft cohesion: 1.05 * sum_r < d < 2.5 * sum_r
        coh_mask = (dist > 1.05 * sum_r) & (dist < 2.5 * sum_r)
        f_coh = np.where(coh_mask, 1.8 * ((dist - 1.05 * sum_r) / sum_r) * dir_ij, 0.0)

        # Core repulsion: d < 0.55 * sum_r (exclude self diagonal)
        eye_mask = np.eye(n_int, dtype=bool)[:, :, None]
        rep_mask = (dist < 0.55 * sum_r) & (~eye_mask)
        f_rep = np.where(rep_mask, 4.5 * ((0.55 * sum_r - dist) / sum_r) * dir_ij, 0.0)

        self.forces[:n_int] += np.sum(f_coh - f_rep, axis=1)

        # 5. Curl-noise drift: trigonometric divergence-free field
        # v_x = d/dy psi, v_y = -d/dx psi
        # psi(x, y) = sin(2*pi*x)*cos(2*pi*y) + 0.5*sin(4*pi*y)
        curl_scale = (1.0 - 0.6 * feat.loudness) * 0.35
        px = self.pos[:, 0]
        py = self.pos[:, 1]
        curl_x = -2.0 * np.pi * np.sin(2.0 * np.pi * px) * np.sin(2.0 * np.pi * py) + 2.0 * np.pi * 0.5 * np.cos(4.0 * np.pi * py)
        curl_y = -2.0 * np.pi * np.cos(2.0 * np.pi * px) * np.cos(2.0 * np.pi * py)
        self.forces[:, 0] += curl_x * curl_scale
        self.forces[:, 1] += curl_y * curl_scale

        # 6. Viscous drag: -c_drag * v
        c_drag = 2.4 * self.viscosity
        self.forces -= c_drag * self.vel

        # 7. Semi-implicit Euler integration
        self.vel += (self.forces / self.weights[:, None]) * dt
        # Velocity cap for safety
        v_norm = np.linalg.norm(self.vel, axis=1, keepdims=True) + 1e-5
        v_scale = np.minimum(1.0, 6.0 / v_norm)
        self.vel *= v_scale

        self.pos += self.vel * dt

        # 8. Boundary wall confinement (radius 0.92)
        pos_dist = np.linalg.norm(self.pos, axis=1)
        wall_mask = pos_dist > self.boundary_r
        if np.any(wall_mask):
            for i in np.where(wall_mask)[0]:
                d = pos_dist[i]
                norm_dir = self.pos[i] / d
                # Cubic restoring force + damp velocity
                penetration = d - self.boundary_r
                self.pos[i] -= norm_dir * penetration
                # Damped reflection
                v_dot_n = float(np.dot(self.vel[i], norm_dir))
                if v_dot_n > 0.0:
                    self.vel[i] -= (1.0 + 0.20) * v_dot_n * norm_dir

    def get_blobs_uniform_data(self) -> np.ndarray:
        """Pack 64 droplets into float32 array of shape (64, 4) for GLSL uBlobs: vec4(x, y, r, weight)."""
        data = np.zeros((self.n_blobs, 4), dtype=np.float32)
        data[:, 0:2] = self.pos
        data[:, 2] = self.r
        data[:, 3] = self.weights
        return data

    def get_magnets_uniform_data(self) -> np.ndarray:
        """Pack 19 electromagnets into float32 array of shape (19, 4) for GLSL uMagnets: vec4(x, y, strength, 0)."""
        data = np.zeros((self.n_magnets, 4), dtype=np.float32)
        data[:, 0:2] = self.magnet_pos
        data[:, 2] = self.magnet_str
        return data
