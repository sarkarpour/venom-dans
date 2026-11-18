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
        self.max_flying = 14
        self._apply_preset_params(preset)

        # Droplet hierarchy: 64 droplets total
        # 6 core blobs (r0: 0.10..0.155, weight: 1.0)
        # 22 satellite chunks (r0: 0.055..0.095, weight: 0.90)
        # 36 droplets / micro-chunks (r0: 0.025..0.048, weight: 0.78)
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

        # Pinch-off (tear-off) and coalescence (re-attaching) state tracking
        self.detached = np.zeros(self.n_blobs, dtype=bool)
        self.detach_timer = np.zeros(self.n_blobs, dtype=np.float32)
        self.target_flight_time = np.zeros(self.n_blobs, dtype=np.float32)
        self.cooldown = np.zeros(self.n_blobs, dtype=np.float32)
        self.pinch_accumulator = 0.0

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
        self._core_mask = np.zeros((self.n_blobs, self.n_blobs), dtype=bool)
        self._core_mask[:self.n_core, :self.n_core] = True
        self._core_mask[np.eye(self.n_blobs, dtype=bool)] = False

        # Audio impulse edge tracking
        self.prev_kick = 0.0
        self.prev_snare = 0.0
        self.prev_hat = 0.0

        # Boundary confinement
        self.boundary_r = 0.76
        self.support_scale = 1.840202

        # Initialize droplet hierarchy
        self._init_droplets()

    def _apply_preset_params(self, preset: str) -> None:
        self.preset = preset
        if preset == "calm":
            self.viscosity = 1.35
            self.magnet_gain = 0.55
            self.kick_impulse = 0.65
            self.spike_amount = 0.20
            self.max_flying = 8
        elif preset == "cinematic":
            self.viscosity = 1.20
            self.magnet_gain = 0.90
            self.kick_impulse = 1.10
            self.spike_amount = 0.45
            self.max_flying = 14
        else:  # "club"
            self.viscosity = 1.00
            self.magnet_gain = 0.70
            self.kick_impulse = 0.95
            self.spike_amount = 0.35
            self.max_flying = 20

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
        self.detached.fill(False)
        self.detach_timer.fill(0.0)
        self.target_flight_time.fill(0.0)
        self.cooldown.fill(0.0)
        self.pinch_accumulator = 0.0

        # 6 core blobs forming the undulating mother mass
        for i in range(self.n_core):
            r_val = float(self.rng.uniform(0.10, 0.155))
            self.r0[i] = r_val
            self.r[i] = r_val
            self.r_target[i] = r_val
            self.weights[i] = 1.0
            angle = float(self.rng.uniform(0, 2 * math.pi))
            dist = float(self.rng.uniform(0.02, 0.06))
            self.pos[i] = [dist * math.cos(angle), dist * math.sin(angle)]

        # 22 sizable satellite chunks that can tear off and reattach
        for i in range(self.n_core, self.n_core + self.n_sat):
            r_val = float(self.rng.uniform(0.055, 0.095))
            self.r0[i] = r_val
            self.r[i] = r_val
            self.r_target[i] = r_val
            self.weights[i] = 0.90
            angle = float(self.rng.uniform(0, 2 * math.pi))
            dist = float(self.rng.uniform(0.16, 0.25))
            self.pos[i] = [dist * math.cos(angle), dist * math.sin(angle)]

        # 36 mist droplets / micro-chunks
        for i in range(self.n_core + self.n_sat, self.n_blobs):
            r_val = float(self.rng.uniform(0.025, 0.048))
            self.r0[i] = r_val
            self.r[i] = r_val
            self.r_target[i] = r_val
            self.weights[i] = 0.78
            angle = float(self.rng.uniform(0, 2 * math.pi))
            dist = float(self.rng.uniform(0.14, 0.23))
            self.pos[i] = [dist * math.cos(angle), dist * math.sin(angle)]

        # Initialize a selection of droplets as detached so the widget has immediate organic life on startup
        init_detached_idx = [7, 10, 14, 18, 22, 26, 32, 38, 44, 50, 56, 62]
        for idx in init_detached_idx:
            self.detached[idx] = True
            self.target_flight_time[idx] = float(self.rng.uniform(1.8, 3.2))
            self.detach_timer[idx] = float(self.rng.uniform(0.2, 1.2))
            angle = float(self.rng.uniform(0, 2 * math.pi))
            dist = float(self.rng.uniform(0.30, 0.50))
            self.pos[idx] = [dist * math.cos(angle), dist * math.sin(angle)]

    def inject_typing_impulse(self, strength: float = 1.0) -> None:
        """Inject a sharp impulse from a keystroke: sprouts Rosensweig spikes and pulses fluid radii."""
        s = float(max(0.1, min(3.0, strength)))
        # 1. Sprout sharp Rosensweig spikes
        self.spike_vel = float(min(45.0, self.spike_vel + 18.0 * s))
        self.spike = float(min(1.8, self.spike + 0.40 * s))

        # 2. Fluid pulse: expand droplet radii with kinetic energy jump
        r_kick = self.rng.uniform(0.15, 0.32, size=self.n_blobs).astype(np.float32) * s
        self.r_vel += r_kick

        # 3. Pulse electromagnet field
        self.magnet_str[0] = float(min(3.2, self.magnet_str[0] + 0.85 * s))
        rand_mag = int(self.rng.integers(1, self.n_magnets))
        self.magnet_str[rand_mag] = float(min(2.5, self.magnet_str[rand_mag] + 1.2 * s))

        # 4. Fling occasional satellite droplet if space available
        n_flying = int(np.sum(self.detached[self.n_core:]))
        if n_flying < self.max_flying and self.rng.random() < 0.35:
            p_core = np.mean(self.pos[:self.n_core], axis=0)
            attached_indices = (
                np.where((~self.detached[self.n_core:]) & (self.cooldown[self.n_core:] <= 0.0))[0]
                + self.n_core
            )
            if len(attached_indices) > 0:
                c = int(self.rng.choice(attached_indices))
                self.detached[c] = True
                self.detach_timer[c] = 0.0
                self.target_flight_time[c] = float(self.rng.uniform(1.0, 2.2))
                rel = self.pos[c] - p_core
                d_rel = float(np.linalg.norm(rel) + 1e-4)
                rad = rel / d_rel
                tang = np.array([-rad[1], rad[0]], dtype=np.float32)
                scatter = float(self.rng.uniform(-0.4, 0.4))
                dir_vec = rad + scatter * tang
                dir_vec /= float(np.linalg.norm(dir_vec) + 1e-4)
                self.vel[c] = dir_vec * float(self.rng.uniform(2.8, 4.5)) * s

    def update_choreography(self, feat: Features, delta_seconds: float) -> None:
        """Run fixed 240 Hz substeps for frame delta time (clamped to 0.1s max)."""
        clamped_dt = min(delta_seconds, 0.10)
        self.accumulated_dt += clamped_dt

        # Check for impulse triggers on positive edges
        kick_jump = max(0.0, feat.kick - self.prev_kick)
        snare_jump = max(0.0, feat.snare - self.prev_snare)
        _hat_jump = max(0.0, feat.hat - self.prev_hat)
        self.prev_kick = feat.kick
        self.prev_snare = feat.snare
        self.prev_hat = feat.hat

        # Update magnets based on audio bands
        # Center magnet: steady baseline anchor keeping mother mass centered, plus audio reactivity
        self.magnet_str[0] = (0.65 + 0.35 * feat.sub + 0.25 * feat.kick) * self.magnet_gain

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
        idle_breath = 0.04 * math.sin(2.5 * self.time)
        for i in range(self.n_blobs):
            band_val = feat.bands[i % len(feat.bands)]
            self.r_target[i] = self.r0[i] * (1.0 + 0.08 * band_val + 0.10 * feat.bass + idle_breath)

        # Global Rosensweig spike target (soft, organic fluid crests)
        spike_target_val = (
            min(1.0, 0.45 * feat.bass + 0.55 * feat.sub + 0.45 * feat.kick) * self.spike_amount
        )
        self.spike_target = spike_target_val

        # Pinch-off (tear-off) event triggers:
        # Mother blob center
        p_core = np.mean(self.pos[:self.n_core], axis=0)
        n_flying = int(np.sum(self.detached[self.n_core:]))

        # A. Audio Transient Tear-Off Trigger: Kicks and Snares fling chunks outward
        if (kick_jump > 0.08 or (feat.kick > 0.55 and kick_jump > 0.03)) and n_flying < self.max_flying:
            attached_indices = np.where((~self.detached[self.n_core:]) & (self.cooldown[self.n_core:] <= 0.0))[0] + self.n_core
            if len(attached_indices) > 0:
                cand_pos = self.pos[attached_indices]
                dists = np.sqrt(np.sum((cand_pos - p_core)**2, axis=1))
                order = np.argsort(-dists)
                candidates = attached_indices[order]
                kj = max(kick_jump, feat.kick * 0.40)
                allowed = self.max_flying - n_flying
                if kj > 0.30:
                    n_eject = min(len(candidates), min(allowed, 4))
                elif kj > 0.18:
                    n_eject = min(len(candidates), min(allowed, 2))
                else:
                    n_eject = min(len(candidates), min(allowed, 1))
                for k in range(n_eject):
                    c = candidates[k]
                    self.detached[c] = True
                    self.detach_timer[c] = 0.0
                    self.target_flight_time[c] = float(self.rng.uniform(1.4, 2.8)) * (1.0 + 0.25 * feat.kick)
                    rel = self.pos[c] - p_core
                    d_rel = np.linalg.norm(rel) + 1e-4
                    rad = rel / d_rel
                    tang = np.array([-rad[1], rad[0]], dtype=np.float32)
                    scatter = float(self.rng.uniform(-0.50, 0.50))
                    dir_vec = rad + scatter * tang
                    dir_vec /= (np.linalg.norm(dir_vec) + 1e-4)
                    speed = (2.8 + 3.2 * kj) * self.kick_impulse
                    self.vel[c] = dir_vec * speed
                n_flying += n_eject

        if snare_jump > 0.14 and n_flying < self.max_flying:
            attached_indices = np.where((~self.detached[self.n_core:]) & (self.cooldown[self.n_core:] <= 0.0))[0] + self.n_core
            if len(attached_indices) > 0:
                c = self.rng.choice(attached_indices)
                self.detached[c] = True
                self.detach_timer[c] = 0.0
                self.target_flight_time[c] = float(self.rng.uniform(1.2, 2.4))
                rel = self.pos[c] - p_core
                d_rel = np.linalg.norm(rel) + 1e-4
                rad = rel / d_rel
                tang = np.array([-rad[1], rad[0]], dtype=np.float32)
                dir_vec = 0.35 * rad + 0.90 * tang
                dir_vec /= (np.linalg.norm(dir_vec) + 1e-4)
                speed = 2.6 + 2.2 * snare_jump
                self.vel[c] = dir_vec * speed
                n_flying += 1

        # B. Ambient / Periodic Pinch-Off (Even in idle/calm, droplets organically tear off)
        self.pinch_accumulator += clamped_dt
        interval = 0.45 / (1.0 + 1.2 * feat.loudness + 0.5 * feat.bass)
        if self.preset == "calm":
            interval *= 1.4

        if self.pinch_accumulator >= interval:
            self.pinch_accumulator = 0.0
            if n_flying < self.max_flying:
                attached_indices = np.where((~self.detached[self.n_core:]) & (self.cooldown[self.n_core:] <= 0.0))[0] + self.n_core
                if len(attached_indices) > 0:
                    cand_pos = self.pos[attached_indices]
                    dists = np.sqrt(np.sum((cand_pos - p_core)**2, axis=1))
                    c = attached_indices[np.argmax(dists)]
                    self.detached[c] = True
                    self.detach_timer[c] = 0.0
                    self.target_flight_time[c] = float(self.rng.uniform(1.5, 3.0))
                    rel = self.pos[c] - p_core
                    d_rel = np.linalg.norm(rel) + 1e-4
                    rad = rel / d_rel
                    tang = np.array([-rad[1], rad[0]], dtype=np.float32)
                    scatter = float(self.rng.uniform(-0.40, 0.40))
                    dir_vec = rad + scatter * tang
                    dir_vec /= (np.linalg.norm(dir_vec) + 1e-4)
                    speed = float(self.rng.uniform(2.2, 3.4))
                    self.vel[c] = dir_vec * speed

        # Substep integration
        while self.accumulated_dt >= self.dt:
            self._substep(feat)
            self.accumulated_dt -= self.dt
            self.time += self.dt

    def _substep(self, feat: Features) -> None:
        """Single 240 Hz semi-implicit Euler integration step with zero heap churn."""
        dt = self.dt
        self.forces.fill(0.0)

        # 1. Update underdamped spring ODEs
        # Radii springs: x'' + 2*zeta*omega*x' + omega^2*(x - x_target) = 0
        r_acc = -2.0 * self.r_zeta * self.r_omega * self.r_vel - (self.r_omega**2) * (self.r - self.r_target)
        self.r_vel += r_acc * dt
        self.r += self.r_vel * dt
        np.clip(self.r, 0.015, 0.35, out=self.r)

        # Spike amount spring: zeta = 0.45, omega = 24.0 rad/s
        spike_acc = (
            -2.0 * self.spike_zeta * self.spike_omega * self.spike_vel
            - (self.spike_omega**2) * (self.spike - self.spike_target)
        )
        self.spike_vel += spike_acc * dt
        self.spike += self.spike_vel * dt
        self.spike = float(np.clip(self.spike, 0.0, 2.0))

        # 2. Update Cooldowns and Compute Core Center of Mass
        self.cooldown = np.maximum(0.0, self.cooldown - dt)
        self.detach_timer[self.detached] += dt
        p_core = np.mean(self.pos[:self.n_core], axis=0)

        # Core Mass Centering: pull mother puddle towards (0, 0) to prevent wandering to window edges
        d_pcore = float(np.linalg.norm(p_core))
        if d_pcore > 0.01:
            self.forces[:self.n_core] -= 4.5 * p_core

        # 3. Fully Vectorized Droplet Flight, Restoring Spring, Coalescence ("دوباره بچسبه"), and Perimeter Tether
        rel = self.pos[self.n_core:] - p_core  # shape (58, 2)
        dist_c = np.sqrt(rel[:, 0]**2 + rel[:, 1]**2) + 1e-5
        inv_u = -rel / dist_c[:, None]  # unit vector pointing towards p_core

        sat_detached = self.detached[self.n_core:]
        sat_r = self.r[self.n_core:]

        # A. Detached Droplets: Free outward flight into chamber, then gentle ramping inward restoring pull
        flight_target = np.maximum(self.target_flight_time[self.n_core:], 0.1)
        tau = self.detach_timer[self.n_core:] / flight_target
        ramp = np.clip((tau - 0.60) / 0.35, 0.0, 1.0)
        # Gentle return force so droplets can float and dance across the chamber
        k_return = np.where(sat_detached, 0.15 + 1.8 * ramp, 0.0)
        self.forces[self.n_core:] += inv_u * (k_return[:, None] * dist_c[:, None])

        # B. Coalescence / Re-attachment check ("دوباره بچسبه")
        # Inward velocity toward mother mass center
        sat_vel = self.vel[self.n_core:]
        v_inward = sat_vel[:, 0] * inv_u[:, 0] + sat_vel[:, 1] * inv_u[:, 1]
        coalesce_mask = (
            sat_detached
            & (self.detach_timer[self.n_core:] > 0.45)
            & (dist_c < (0.15 + sat_r))
            & (v_inward > 0.0)
        )
        if np.any(coalesce_mask):
            coal_local = np.where(coalesce_mask)[0]
            coal_global = coal_local + self.n_core
            self.detached[coal_global] = False
            self.detach_timer[coal_global] = 0.0
            self.cooldown[coal_global] = self.rng.uniform(0.25, 0.65, size=len(coal_global))

            # Momentum absorption & recoil impulse to mother mass
            recoil = np.sum(self.weights[coal_global, None] * self.vel[coal_global] * 0.70, axis=0)
            self.vel[coal_global] *= 0.25
            self.vel[:self.n_core] += (recoil / (self.n_core * self.weights[0])) * 0.15

        # C. Attached Droplets: Natural perimeter tether & stretch pinch-off
        target_d = 0.17 + 0.05 * np.sin(np.arange(self.n_core, self.n_blobs) * 1.3)
        excess_d = np.maximum(0.0, dist_c - target_d)
        k_tether = np.where(~sat_detached, 3.8, 0.0)
        self.forces[self.n_core:] += inv_u * (k_tether[:, None] * excess_d[:, None])

        # Stretch pinch-off: if an attached droplet is pulled into outer chamber while moving outward
        n_flying = int(np.count_nonzero(sat_detached))
        if n_flying < self.max_flying:
            stretch_candidates = np.where(
                (~sat_detached)
                & (dist_c > (0.35 + sat_r))
                & (v_inward < -0.2)
                & (self.cooldown[self.n_core:] <= 0.0)
            )[0]
            if len(stretch_candidates) > 0:
                str_pick = stretch_candidates[np.argmax(dist_c[stretch_candidates])]
                g_str = str_pick + self.n_core
                self.detached[g_str] = True
                self.detach_timer[g_str] = 0.0
                self.target_flight_time[g_str] = float(self.rng.uniform(1.6, 3.0))

        # 4. Magnetic Attraction: Vectorized across all 19 magnets
        eps2 = 0.08**2
        G = 4.2
        dx_m = self.magnet_pos[None, :, 0] - self.pos[:, None, 0]  # (64, 19)
        dy_m = self.magnet_pos[None, :, 1] - self.pos[:, None, 1]  # (64, 19)
        dist2_m = dx_m * dx_m + dy_m * dy_m
        denom_m = np.power(dist2_m + eps2, 1.25)

        fm_x = G * (self.magnet_str[None, :] * dx_m) / denom_m
        fm_y = G * (self.magnet_str[None, :] * dy_m) / denom_m

        # Center magnet (index 0) pulls core blobs and returning droplets, but is attenuated
        # during outward flight of detached droplets so they can escape into the chamber
        if np.any(self.detached):
            early_flight = self.detached & (self.detach_timer < 0.50 * np.maximum(self.target_flight_time, 0.1))
            fm_x[early_flight, 0] *= 0.10
            fm_y[early_flight, 0] *= 0.10

        flen = np.sqrt(fm_x * fm_x + fm_y * fm_y) + 1e-5
        scale_m = np.minimum(1.0, 15.0 / flen)
        self.forces[:, 0] += np.sum(fm_x * scale_m, axis=1)
        self.forces[:, 1] += np.sum(fm_y * scale_m, axis=1)

        # 5. Pairwise droplet interactions (Surface Tension Cohesion + Repulsion)
        dx = self.pos[:, 0:1].T - self.pos[:, 0:1]  # dx[i, j] = pos[j] - pos[i]
        dy = self.pos[:, 1:2].T - self.pos[:, 1:2]
        d2 = dx * dx + dy * dy
        dist = np.sqrt(d2) + 1e-5
        inv_d = 1.0 / dist
        dir_x = dx * inv_d
        dir_y = dy * inv_d

        sum_r = self.r[:, None] + self.r[None, :]

        # Cohesion:
        # A. Core-to-core: binds core blobs firmly into the central mother mass
        coh_core = self._core_mask & (dist > 1.05 * sum_r) & (dist < 2.2 * sum_r)
        f_coh_core = np.where(coh_core, 2.5 * ((dist - 1.05 * sum_r) / sum_r), 0.0)

        # B. Attached-to-attached cohesion: binds attached satellite droplets into the mother mass
        attached_mask = (~self.detached)[:, None] & (~self.detached)[None, :] & self._not_diagonal
        coh_att = attached_mask & (~self._core_mask) & (dist > 1.05 * sum_r) & (dist < 2.0 * sum_r)
        f_coh_att = np.where(coh_att, 1.8 * ((dist - 1.05 * sum_r) / sum_r), 0.0)

        # Repulsion:
        # Core & attached: soft repulsion prevents collapse
        # Detached-detached: wider repulsion keeps flying droplets separate in the chamber
        det_det_mask = self.detached[:, None] & self.detached[None, :] & self._not_diagonal
        rep_thresh = np.where(det_det_mask, 1.35 * sum_r, 0.80 * sum_r)
        rep_m = self._not_diagonal & (dist < rep_thresh)
        f_rep = np.where(rep_m, 4.5 * ((rep_thresh - dist) / sum_r), 0.0)

        f_net = (f_coh_core + f_coh_att) - f_rep
        self.forces[:, 0] += np.sum(f_net * dir_x, axis=1)
        self.forces[:, 1] += np.sum(f_net * dir_y, axis=1)

        # 6. Continuous swirling vortex + Curl-noise drift
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

        # 6.5. Progressive inward boundary cushion: smoothly decelerate droplets approaching chamber edge
        safe_chamber_r = 0.80
        max_r_center = np.maximum(0.35, safe_chamber_r - self.r * self.support_scale)
        pos_dist_cur = np.sqrt(self.pos[:, 0]**2 + self.pos[:, 1]**2)
        cushion_zone = 0.12
        soft_r = np.maximum(0.20, max_r_center - cushion_zone)
        cush_mask = pos_dist_cur > soft_r
        if np.any(cush_mask):
            inv_p = 1.0 / np.maximum(pos_dist_cur, 1e-5)
            nx = self.pos[:, 0] * inv_p
            ny = self.pos[:, 1] * inv_p
            cush_ratio = np.clip((pos_dist_cur - soft_r) / cushion_zone, 0.0, 1.0)
            f_cush = -5.5 * (cush_ratio**1.5)
            self.forces[:, 0] += np.where(cush_mask, f_cush * nx, 0.0)
            self.forces[:, 1] += np.where(cush_mask, f_cush * ny, 0.0)

        # 7. Viscous drag: -c_drag * v
        c_drag = 2.4 * self.viscosity
        self.forces -= c_drag * self.vel

        # 8. Semi-implicit Euler integration
        self.vel += (self.forces / self.weights[:, None]) * dt
        v_sq = self.vel[:, 0]**2 + self.vel[:, 1]**2
        v_norm = np.sqrt(v_sq)[:, None] + 1e-5
        v_scale = np.minimum(1.0, 6.0 / v_norm)
        self.vel *= v_scale

        self.pos += self.vel * dt

        # 9. Boundary chamber confinement (guarantees zero window-edge clipping) - Vectorized
        pos_dist = np.sqrt(self.pos[:, 0]**2 + self.pos[:, 1]**2)
        wall_mask = pos_dist > max_r_center
        if np.any(wall_mask):
            inv_pdist = 1.0 / np.maximum(pos_dist, 1e-5)
            norm_x = self.pos[:, 0] * inv_pdist
            norm_y = self.pos[:, 1] * inv_pdist
            penetration = np.maximum(0.0, pos_dist - max_r_center)

            self.pos[:, 0] -= norm_x * penetration
            self.pos[:, 1] -= norm_y * penetration

            v_dot_n = self.vel[:, 0] * norm_x + self.vel[:, 1] * norm_y
            reflect_mask = wall_mask & (v_dot_n > 0.0)
            self.vel[:, 0] -= np.where(reflect_mask, 1.25 * v_dot_n * norm_x, 0.0)
            self.vel[:, 1] -= np.where(reflect_mask, 1.25 * v_dot_n * norm_y, 0.0)

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
