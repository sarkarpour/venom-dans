"""Deterministic synthetic audio test signals at 48,000 Hz stereo."""

from __future__ import annotations

import numpy as np


def generate_synthetic_audio(name: str, duration_sec: float = 5.0, sample_rate: int = 48000) -> np.ndarray:
    """Generate stereo float32 audio signal of given duration and sample rate.

    Returns:
        np.ndarray with shape (num_samples, 2), dtype np.float32.
    """
    num_samples = int(duration_sec * sample_rate)
    t = np.linspace(0.0, duration_sec, num_samples, endpoint=False, dtype=np.float32)
    output = np.zeros((num_samples, 2), dtype=np.float32)

    if name == "silence":
        return output

    if name == "kick120":
        # 120 BPM = 2 beats per second = 0.5 sec period
        beat_period = 0.5
        phase = np.mod(t, beat_period)
        # Integrated phase for instantaneous frequency (drops from 160 Hz to 45 Hz)
        # Integral of 45*t + 115 * (-0.04 * exp(-t/0.04))
        osc_phase = 2.0 * np.pi * (45.0 * phase - 115.0 * 0.04 * np.exp(-phase / 0.04))
        amp_env = np.exp(-phase / 0.09) * np.clip(1.0 - phase / 0.45, 0.0, 1.0)
        kick = (np.sin(osc_phase) * amp_env).astype(np.float32)
        output[:, 0] = kick * 0.9
        output[:, 1] = kick * 0.9

    elif name == "bass_sweep":
        # Logarithmic sweep from 30 Hz to 500 Hz
        f0 = 30.0
        f1 = 500.0
        rate = np.log(f1 / f0) / max(duration_sec, 0.001)
        phase = 2.0 * np.pi * f0 * (np.exp(rate * t) - 1.0) / rate
        sweep = 0.8 * np.sin(phase).astype(np.float32)
        output[:, 0] = sweep
        output[:, 1] = sweep

    elif name == "noise_bursts":
        # Noise bursts every 0.25 s with 0.05 s decay
        rng = np.random.Generator(np.random.PCG64(42))
        raw_noise = rng.standard_normal(num_samples).astype(np.float32)
        burst_period = 0.25
        phase = np.mod(t, burst_period)
        env = np.exp(-phase / 0.035).astype(np.float32)
        bursts = np.clip(raw_noise * env * 0.7, -1.0, 1.0)
        output[:, 0] = bursts
        output[:, 1] = bursts

    elif name == "full_mix":
        # Comprehensive mix: 120 BPM Kick + 8th note Hi-hats + Snare on 2 and 4 + 75 Hz sub bass
        rng = np.random.Generator(np.random.PCG64(1337))
        white_noise = rng.standard_normal(num_samples).astype(np.float32)

        # 1. Kick (every 0.5s)
        kick_phase = np.mod(t, 0.5)
        kick_osc = np.sin(2.0 * np.pi * (48.0 * kick_phase - 110.0 * 0.035 * np.exp(-kick_phase / 0.035)))
        kick_env = np.exp(-kick_phase / 0.08) * np.clip(1.0 - kick_phase / 0.4, 0.0, 1.0)
        kick = (kick_osc * kick_env * 0.85).astype(np.float32)

        # 2. Snare (every 1.0s, offset by 0.5s -> on beat 2)
        snare_t = np.mod(t + 0.5, 1.0)
        snare_env = np.exp(-snare_t / 0.07).astype(np.float32)
        snare_tone = np.sin(2.0 * np.pi * 185.0 * snare_t) * np.exp(-snare_t / 0.05)
        snare = (0.6 * white_noise * snare_env + 0.4 * snare_tone * snare_env).astype(np.float32)

        # 3. Hi-hat (every 0.125s, high passed)
        hat_t = np.mod(t, 0.125)
        hat_env = np.exp(-hat_t / 0.015).astype(np.float32)
        # Simple high pass filter on noise for crisp hats
        hp_noise = white_noise - np.roll(white_noise, 1)
        hat = (hp_noise * hat_env * 0.35).astype(np.float32)

        # 4. Bassline: 70 Hz sine with 8th note groove
        bass_note = np.sin(2.0 * np.pi * 70.0 * t) * (0.35 + 0.25 * np.sin(2.0 * np.pi * 4.0 * t))

        left = kick * 0.85 + snare * 0.7 + hat * 0.4 + bass_note * 0.5
        right = kick * 0.85 + snare * 0.7 + hat * 0.4 + bass_note * 0.5
        # Slight stereo panning on hat
        left += hat * 0.1
        right -= hat * 0.1

        output[:, 0] = np.clip(left, -1.0, 1.0)
        output[:, 1] = np.clip(right, -1.0, 1.0)
    else:
        # Default fallback to 220 Hz sine
        sine = 0.5 * np.sin(2.0 * np.pi * 220.0 * t).astype(np.float32)
        output[:, 0] = sine
        output[:, 1] = sine

    return output
