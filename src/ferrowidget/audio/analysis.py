"""Audio DSP analysis pipeline: Hann STFT, 32 log bands, AGC, onsets, beat tracking."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Features:
    """Immutable snapshot of audio features published to the GUI/render thread."""
    bands: tuple[float, ...]  # 32 log bands, 0..1
    sub: float                # 30-60 Hz
    bass: float               # 60-250 Hz
    lowmid: float             # 250-500 Hz
    mid: float                # 500-2000 Hz
    highmid: float            # 2000-6000 Hz
    air: float                # 6000-16000 Hz
    loudness: float           # 0..1 overall normalized RMS
    centroid: float           # 0..1 normalized spectral centroid
    balance: float            # -1..1 stereo balance
    excitement: float         # 0..1 smoothed energy (~6s EMA)
    kick: float               # 0..1 kick impulse envelope
    snare: float              # 0..1 snare impulse envelope
    hat: float                # 0..1 hat impulse envelope
    beat_phase: float         # 0..1 continuous tempo-locked phase
    is_silent: bool           # True if silence > 1.5s


class AudioAnalyzer:
    """Zero-heap-churn audio feature extractor operating in 512-sample hops at 48 kHz."""

    def __init__(self, sample_rate: int = 48000, n_fft: int = 2048, hop_size: int = 512, sensitivity: float = 1.0):
        self.sample_rate = sample_rate
        self.n_fft = n_fft
        self.hop_size = hop_size
        self.sensitivity = max(0.1, float(sensitivity))
        self.dt = hop_size / float(sample_rate)

        # Preallocated buffers
        self.window = np.hanning(n_fft).astype(np.float32)
        self.input_ring = np.zeros(n_fft, dtype=np.float32)
        self.fft_in = np.zeros(n_fft, dtype=np.float32)
        self.num_bins = n_fft // 2 + 1
        self.freqs = np.linspace(0, sample_rate / 2, self.num_bins, dtype=np.float32)

        # 32 Logarithmic Bands from 30 Hz to 16000 Hz
        self.num_bands = 32
        self.f_min = 30.0
        self.f_max = 16000.0
        self.band_centers = np.geomspace(self.f_min, self.f_max, self.num_bands).astype(np.float32)
        self.filterbank = self._build_filterbank()

        # Pink noise tilt (+3 dB / octave above 250 Hz)
        self.pink_tilt = 3.0 * np.log2(self.band_centers / 250.0).astype(np.float32)

        # AGC tracking state per band
        self.floor = np.full(self.num_bands, -60.0, dtype=np.float32)
        self.ceiling = np.full(self.num_bands, -20.0, dtype=np.float32)
        self.env_smooth = np.zeros(self.num_bands, dtype=np.float32)

        # Filter band grouping masks
        self.mask_sub = (self.band_centers >= 30.0) & (self.band_centers < 60.0)
        self.mask_bass = (self.band_centers >= 60.0) & (self.band_centers < 250.0)
        self.mask_lowmid = (self.band_centers >= 250.0) & (self.band_centers < 500.0)
        self.mask_mid = (self.band_centers >= 500.0) & (self.band_centers < 2000.0)
        self.mask_highmid = (self.band_centers >= 2000.0) & (self.band_centers < 6000.0)
        self.mask_air = (self.band_centers >= 6000.0) & (self.band_centers <= 16000.0)

        # Onset detection states (kick, snare, hat)
        self.prev_band_db = np.full(self.num_bands, -80.0, dtype=np.float32)

        # Sliding history for adaptive median + k*MAD thresholds (~1.0s = 94 hops)
        self.history_len = 94
        self.flux_history_kick = np.zeros(self.history_len, dtype=np.float32)
        self.flux_history_snare = np.zeros(self.history_len, dtype=np.float32)
        self.flux_history_hat = np.zeros(self.history_len, dtype=np.float32)
        self.hist_idx = 0

        self.kick_env = 0.0
        self.snare_env = 0.0
        self.hat_env = 0.0

        self.last_kick_time = -1.0
        self.last_snare_time = -1.0
        self.last_hat_time = -1.0
        self.current_time = 0.0

        # Silence detector
        self.silent_duration = 0.0

        # Excitement EMA (~6s)
        self.excitement = 0.0
        self.alpha_exc = 1.0 - math.exp(-self.dt / 6.0)

        # Beat tracking
        self.beat_phase = 0.0
        self.bpm = 120.0

        # Visual delay line buffer (up to 500ms = ~48 hops)
        self.delay_hops = 0
        self.feature_delay_line: list[Features] = []

        # Current published feature snapshot
        self.current_features = self._make_default_features()

    def _build_filterbank(self) -> np.ndarray:
        """Construct smooth overlapping triangular filterbank ensuring no empty bands."""
        f_edges = np.geomspace(self.f_min * 0.85, self.f_max * 1.15, self.num_bands + 2)
        fb = np.zeros((self.num_bands, self.num_bins), dtype=np.float32)

        for i in range(self.num_bands):
            f_low = f_edges[i]
            f_center = f_edges[i + 1]
            f_high = f_edges[i + 2]

            # Linear interpolation in log-frequency space
            for bin_idx, f_bin in enumerate(self.freqs):
                if f_bin >= f_low and f_bin <= f_center:
                    fb[i, bin_idx] = (f_bin - f_low) / max(f_center - f_low, 1e-4)
                elif f_bin > f_center and f_bin <= f_high:
                    fb[i, bin_idx] = (f_high - f_bin) / max(f_high - f_center, 1e-4)

            # Ensure lower bands with very few bins still have non-zero energy
            total = np.sum(fb[i])
            if total > 0.0:
                fb[i] /= total
            else:
                # Fallback to nearest bin
                nearest = np.argmin(np.abs(self.freqs - self.band_centers[i]))
                fb[i, nearest] = 1.0

        return fb

    def _make_default_features(self) -> Features:
        return Features(
            bands=tuple([0.0] * self.num_bands),
            sub=0.0,
            bass=0.0,
            lowmid=0.0,
            mid=0.0,
            highmid=0.0,
            air=0.0,
            loudness=0.0,
            centroid=0.0,
            balance=0.0,
            excitement=0.0,
            kick=0.0,
            snare=0.0,
            hat=0.0,
            beat_phase=0.0,
            is_silent=True,
        )

    def set_visual_delay(self, delay_ms: int) -> None:
        """Set visual latency compensation in milliseconds (0..500 ms)."""
        hops = int(round(delay_ms / (self.dt * 1000.0)))
        self.delay_hops = max(0, min(50, hops))

    def process_hop(self, hop_samples: np.ndarray) -> Features:
        """Process 512 stereo samples (512, 2) in <= 1.0 ms and return Features."""
        self.current_time += self.dt

        # 1. Stereo energy and balance
        left = hop_samples[:, 0]
        right = hop_samples[:, 1]
        rms_l = float(np.sqrt(np.mean(left * left) + 1e-12))
        rms_r = float(np.sqrt(np.mean(right * right) + 1e-12))
        raw_rms = 0.5 * (rms_l + rms_r)

        balance = float((rms_r - rms_l) / (rms_r + rms_l + 1e-6))
        balance = max(-1.0, min(1.0, balance))

        # Silence detection (< -70 dBFS ~ 0.000316)
        raw_db = 20.0 * math.log10(max(raw_rms, 1e-6))
        if raw_db < -70.0:
            self.silent_duration += self.dt
        else:
            self.silent_duration = 0.0
        is_silent = self.silent_duration > 1.5

        # 2. Mono mix & sliding STFT window
        mono = 0.5 * (left + right)
        self.input_ring[:-self.hop_size] = self.input_ring[self.hop_size:]
        self.input_ring[-self.hop_size:] = mono

        self.fft_in[:] = self.input_ring * self.window
        spec = np.fft.rfft(self.fft_in)
        power = (np.abs(spec) ** 2) / float(self.n_fft)

        # 3. Log filterbank mapping & pink tilt
        band_power = np.dot(self.filterbank, power)
        band_db = 10.0 * np.log10(np.maximum(band_power, 1e-12))
        band_db_tilted = band_db + self.pink_tilt

        # 4. Adaptive Gain Control (AGC)
        # Floor: fast drop, slow rise (~4.5s)
        # Ceiling: fast rise (~30ms), slow drop (~4.5s)
        alpha_ceil_up = 1.0 - math.exp(-self.dt / 0.030)
        alpha_ceil_down = 1.0 - math.exp(-self.dt / 4.50)
        alpha_floor_down = 1.0 - math.exp(-self.dt / 0.030)
        alpha_floor_up = 1.0 - math.exp(-self.dt / 4.50)

        for i in range(self.num_bands):
            val = band_db_tilted[i]
            # Ceiling tracking
            if val > self.ceiling[i]:
                self.ceiling[i] += alpha_ceil_up * (val - self.ceiling[i])
            else:
                self.ceiling[i] += alpha_ceil_down * (val - self.ceiling[i])

            # Floor tracking
            if val < self.floor[i]:
                self.floor[i] += alpha_floor_down * (val - self.floor[i])
            else:
                self.floor[i] += alpha_floor_up * (val - self.floor[i])

        # Dynamic range span min 18 dB
        dyn_span = np.maximum(self.ceiling - self.floor, 18.0)
        norm_bands = np.clip((band_db_tilted - self.floor) / dyn_span, 0.0, 1.0)
        # Gamma 1.3
        norm_bands = np.power(norm_bands, 1.3) * self.sensitivity
        norm_bands = np.clip(norm_bands, 0.0, 1.0)

        # Envelope follower (attack 8 ms, release 150 ms)
        alpha_att = 1.0 - math.exp(-self.dt / 0.008)
        alpha_rel = 1.0 - math.exp(-self.dt / 0.150)
        for i in range(self.num_bands):
            nb = norm_bands[i]
            if nb > self.env_smooth[i]:
                self.env_smooth[i] += alpha_att * (nb - self.env_smooth[i])
            else:
                self.env_smooth[i] += alpha_rel * (nb - self.env_smooth[i])

        # Aggregate band groups
        sub = float(np.mean(self.env_smooth[self.mask_sub]))
        bass = float(np.mean(self.env_smooth[self.mask_bass]))
        lowmid = float(np.mean(self.env_smooth[self.mask_lowmid]))
        mid = float(np.mean(self.env_smooth[self.mask_mid]))
        highmid = float(np.mean(self.env_smooth[self.mask_highmid]))
        air = float(np.mean(self.env_smooth[self.mask_air]))

        # Normalized loudness & spectral centroid
        loudness = float(np.clip(np.mean(self.env_smooth), 0.0, 1.0))
        sum_power = float(np.sum(band_power)) + 1e-12
        centroid_hz = float(np.sum(self.band_centers * band_power) / sum_power)
        centroid = float(np.clip(math.log2(max(centroid_hz, self.f_min) / self.f_min) / math.log2(self.f_max / self.f_min), 0.0, 1.0))

        # Excitement 6s EMA
        self.excitement += self.alpha_exc * (loudness - self.excitement)

        # 5. Onset Detection via Half-wave rectified flux
        flux_bands = np.maximum(0.0, band_db - self.prev_band_db)
        self.prev_band_db[:] = band_db

        # Regions:
        # Kick: 30-150 Hz
        mask_kick_flux = (self.band_centers >= 30.0) & (self.band_centers <= 150.0)
        flux_kick = float(np.sum(flux_bands[mask_kick_flux]))

        # Snare: 150-400 Hz + 2000-8000 Hz
        mask_snare_flux = ((self.band_centers >= 150.0) & (self.band_centers <= 400.0)) | (
            (self.band_centers >= 2000.0) & (self.band_centers <= 8000.0)
        )
        flux_snare = float(np.sum(flux_bands[mask_snare_flux]))

        # Hat: 6000-16000 Hz
        mask_hat_flux = self.band_centers >= 6000.0
        flux_hat = float(np.sum(flux_bands[mask_hat_flux]))

        # Record in history buffer
        self.flux_history_kick[self.hist_idx] = flux_kick
        self.flux_history_snare[self.hist_idx] = flux_snare
        self.flux_history_hat[self.hist_idx] = flux_hat
        self.hist_idx = (self.hist_idx + 1) % self.history_len

        # Adaptive Threshold = median + k * MAD
        # 1. Kick onsets (refractory 90 ms, decay tau = 120 ms)
        self.kick_env *= math.exp(-self.dt / 0.120)
        med_k = float(np.median(self.flux_history_kick))
        mad_k = float(np.median(np.abs(self.flux_history_kick - med_k)))
        thresh_k = med_k + 2.2 * max(mad_k, 2.5)
        if flux_kick > thresh_k and (self.current_time - self.last_kick_time) >= 0.090:
            impulse = float(np.clip((flux_kick - thresh_k) / 12.0, 0.2, 1.0))
            self.kick_env = min(1.0, self.kick_env + impulse)
            self.last_kick_time = self.current_time

        # 2. Snare onsets (refractory 100 ms, decay tau = 160 ms)
        self.snare_env *= math.exp(-self.dt / 0.160)
        med_s = float(np.median(self.flux_history_snare))
        mad_s = float(np.median(np.abs(self.flux_history_snare - med_s)))
        thresh_s = med_s + 2.4 * max(mad_s, 3.0)
        if flux_snare > thresh_s and (self.current_time - self.last_snare_time) >= 0.100:
            impulse = float(np.clip((flux_snare - thresh_s) / 15.0, 0.2, 1.0))
            self.snare_env = min(1.0, self.snare_env + impulse)
            self.last_snare_time = self.current_time

        # 3. Hat onsets (refractory 50 ms, decay tau = 60 ms)
        self.hat_env *= math.exp(-self.dt / 0.060)
        med_h = float(np.median(self.flux_history_hat))
        mad_h = float(np.median(np.abs(self.flux_history_hat - med_h)))
        thresh_h = med_h + 2.0 * max(mad_h, 2.0)
        if flux_hat > thresh_h and (self.current_time - self.last_hat_time) >= 0.050:
            impulse = float(np.clip((flux_hat - thresh_h) / 10.0, 0.2, 1.0))
            self.hat_env = min(1.0, self.hat_env + impulse)
            self.last_hat_time = self.current_time

        # 6. Continuous beat tracking
        # Advance phase by tempo (120 BPM default = 2.0 Hz)
        self.beat_phase = (self.beat_phase + self.dt * (self.bpm / 60.0)) % 1.0
        # Phase lock on clean kick hits
        if flux_kick > thresh_k and self.kick_env > 0.6:
            self.beat_phase = 0.0

        feat = Features(
            bands=tuple(float(x) for x in self.env_smooth),
            sub=sub,
            bass=bass,
            lowmid=lowmid,
            mid=mid,
            highmid=highmid,
            air=air,
            loudness=loudness,
            centroid=centroid,
            balance=balance,
            excitement=float(self.excitement),
            kick=float(np.clip(self.kick_env, 0.0, 1.0)),
            snare=float(np.clip(self.snare_env, 0.0, 1.0)),
            hat=float(np.clip(self.hat_env, 0.0, 1.0)),
            beat_phase=float(self.beat_phase),
            is_silent=is_silent,
        )

        if self.delay_hops > 0:
            self.feature_delay_line.append(feat)
            if len(self.feature_delay_line) > self.delay_hops:
                self.current_features = self.feature_delay_line.pop(0)
            else:
                self.current_features = self._make_default_features()
        else:
            self.current_features = feat

        return self.current_features
