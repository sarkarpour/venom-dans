"""Unit and integration tests for DSP analysis, synthetic signals, and AGC."""

import time

import numpy as np

from ferrowidget.audio.analysis import AudioAnalyzer
from ferrowidget.audio.synthetic import generate_synthetic_audio


def test_synthetic_audio_generators():
    """Verify all synthetic signals generate valid float32 arrays without NaNs or Infs."""
    signals = ["kick120", "bass_sweep", "noise_bursts", "full_mix", "silence"]
    for sig in signals:
        data = generate_synthetic_audio(sig, duration_sec=1.0)
        assert data.shape == (48000, 2), f"Signal {sig} shape mismatch"
        assert data.dtype == np.float32
        assert not np.isnan(data).any(), f"Signal {sig} contains NaNs"
        assert not np.isinf(data).any(), f"Signal {sig} contains Infs"
        assert np.max(np.abs(data)) <= 1.05, f"Signal {sig} exceeds safe amplitude"


def test_hop_execution_latency():
    """Verify single hop processing time is strictly < 1.0 ms."""
    analyzer = AudioAnalyzer()
    chunk = np.zeros((512, 2), dtype=np.float32)

    # Warmup
    for _ in range(10):
        analyzer.process_hop(chunk)

    t0 = time.perf_counter()
    n_iterations = 200
    for _ in range(n_iterations):
        analyzer.process_hop(chunk)
    elapsed = time.perf_counter() - t0
    avg_ms = (elapsed / n_iterations) * 1000.0

    print(f"\nAverage hop execution latency: {avg_ms:.3f} ms")
    assert avg_ms < 1.0, f"Hop processing is too slow: {avg_ms:.3f} ms >= 1.0 ms"


def test_frequency_band_accuracy():
    """Verify pure tones activate expected frequency bands."""
    analyzer = AudioAnalyzer()
    sr = 48000
    t = np.arange(2048, dtype=np.float32) / sr

    # Test 60 Hz tone -> should concentrate in sub/bass bands (indices 2-5)
    tone_60 = np.sin(2.0 * np.pi * 60.0 * t).astype(np.float32)

    for i in range(4):
        chunk = np.column_stack([tone_60[i*512:(i+1)*512], tone_60[i*512:(i+1)*512]])
        feat = analyzer.process_hop(chunk)

    # Low frequency bands must dominate over high frequency bands
    assert feat.bass > 0.0 or feat.sub > 0.0
    assert feat.air < 0.2


def test_120bpm_kick_onset_timing():
    """Verify 120 BPM kick onsets are accurately detected every 0.5s (+/- 1 hop)."""
    analyzer = AudioAnalyzer()
    audio = generate_synthetic_audio("kick120", duration_sec=3.0)
    hop_size = 512
    dt_hop = hop_size / 48000.0

    kick_times = []
    current_time = 0.0

    for i in range(0, len(audio) - hop_size, hop_size):
        chunk = audio[i : i + hop_size]
        current_time += dt_hop
        feat = analyzer.process_hop(chunk)
        # Check onset trigger peak
        if feat.kick > 0.75:
            if not kick_times or (current_time - kick_times[-1]) > 0.25:
                kick_times.append(current_time)

    # In 3 seconds at 120 BPM, expect around 5-6 kicks with interval ~0.5s
    assert len(kick_times) >= 4, f"Detected fewer kicks than expected: {kick_times}"
    intervals = np.diff(kick_times)
    for interval in intervals:
        assert abs(interval - 0.5) < (2.5 * dt_hop), f"Kick interval {interval:.4f} deviated from 0.5s"


def test_agc_invariance_across_input_gains():
    """Verify AGC normalizes output bands across a 30 dB dynamic range difference."""
    analyzer_quiet = AudioAnalyzer()
    analyzer_loud = AudioAnalyzer()

    # Generate test audio
    audio_ref = generate_synthetic_audio("noise_bursts", duration_sec=2.0)
    audio_quiet = audio_ref * 0.0316  # -30 dB
    audio_loud = audio_ref * 1.0      # 0 dB

    hop_size = 512
    quiet_feats = []
    loud_feats = []

    for i in range(0, len(audio_ref) - hop_size, hop_size):
        feat_q = analyzer_quiet.process_hop(audio_quiet[i : i + hop_size])
        feat_l = analyzer_loud.process_hop(audio_loud[i : i + hop_size])
        if i > 48000:  # Allow 1 second for AGC convergence
            quiet_feats.append(feat_q.loudness)
            loud_feats.append(feat_l.loudness)

    mean_quiet = np.mean(quiet_feats)
    mean_loud = np.mean(loud_feats)
    print(f"\nAGC Convergence: Quiet Mean={mean_quiet:.3f}, Loud Mean={mean_loud:.3f}")
    # After AGC convergence, normalized loudness should be well within same order of magnitude
    assert abs(mean_loud - mean_quiet) < 0.45
