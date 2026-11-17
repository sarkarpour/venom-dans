"""Unit and stress tests for 2D fluid simulation and choreography."""

import numpy as np

from ferrowidget.audio.analysis import AudioAnalyzer
from ferrowidget.audio.synthetic import generate_synthetic_audio
from ferrowidget.physics.fluid import FluidSimulation


def test_simulation_determinism():
    """Verify that two simulations with identical seeds produce bit-identical states."""
    sim1 = FluidSimulation(seed=12345, preset="club")
    sim2 = FluidSimulation(seed=12345, preset="club")

    analyzer = AudioAnalyzer()
    audio = generate_synthetic_audio("kick120", duration_sec=1.0)
    feat = analyzer.process_hop(audio[:512])

    for _ in range(60):
        sim1.update_choreography(feat, 1.0 / 60.0)
        sim2.update_choreography(feat, 1.0 / 60.0)

    np.testing.assert_array_equal(sim1.pos, sim2.pos)
    np.testing.assert_array_equal(sim1.vel, sim2.vel)
    np.testing.assert_array_equal(sim1.r, sim2.r)
    assert sim1.spike == sim2.spike


def test_no_nans_and_bounded_energy_over_10_minutes():
    """Run 10 simulated minutes (600 seconds = 36,000 frames) with intense kick audio."""
    sim = FluidSimulation(seed=42, preset="club")
    analyzer = AudioAnalyzer()
    audio = generate_synthetic_audio("full_mix", duration_sec=5.0)

    hop_size = 512
    dt_frame = 1.0 / 60.0

    # Simulate 600 seconds in chunks
    total_sim_seconds = 600.0
    elapsed = 0.0
    audio_idx = 0

    max_kinetic_energy = 0.0

    # Step in 1-second blocks (60 frames per block)
    while elapsed < total_sim_seconds:
        chunk = audio[audio_idx : audio_idx + hop_size]
        audio_idx = (audio_idx + hop_size) % (len(audio) - hop_size)
        feat = analyzer.process_hop(chunk)

        sim.update_choreography(feat, dt_frame)
        elapsed += dt_frame

        # Compute kinetic energy: 0.5 * sum(m * v^2)
        v2 = np.sum(sim.vel * sim.vel, axis=1)
        ke = 0.5 * np.sum(sim.weights * v2)
        if ke > max_kinetic_energy:
            max_kinetic_energy = ke

        # Check safety invariants every 60 frames (1 second) to minimize test overhead
        if int(elapsed * 60) % 60 == 0:
            assert not np.isnan(sim.pos).any(), f"NaN in pos at t={elapsed}s"
            assert not np.isnan(sim.vel).any(), f"NaN in vel at t={elapsed}s"
            assert not np.isnan(sim.r).any(), f"NaN in r at t={elapsed}s"
            assert not np.isnan(sim.spike), f"NaN in spike at t={elapsed}s"

            # Confinement check
            max_dist = np.max(np.linalg.norm(sim.pos, axis=1))
            assert max_dist < 0.96, f"Droplet escaped boundary: max_dist={max_dist:.4f} at t={elapsed}s"

            # Energy must remain stably bounded (no explosions)
            assert ke < 1200.0, f"Kinetic energy explosion: ke={ke:.2f} at t={elapsed}s"

    print(f"\nCompleted 10 simulated minutes! Max KE observed: {max_kinetic_energy:.2f}")


def test_presets():
    """Verify that calm, club, and cinematic apply distinct parameter sets."""
    sim_calm = FluidSimulation(preset="calm")
    sim_club = FluidSimulation(preset="club")
    sim_cine = FluidSimulation(preset="cinematic")

    assert sim_calm.viscosity > sim_club.viscosity
    assert sim_cine.spike_amount > sim_club.spike_amount
    assert sim_cine.magnet_gain > sim_calm.magnet_gain


def test_uniform_buffers_packing():
    """Verify get_blobs_uniform_data and get_magnets_uniform_data shapes and types."""
    sim = FluidSimulation()
    blobs = sim.get_blobs_uniform_data()
    magnets = sim.get_magnets_uniform_data()

    assert blobs.shape == (64, 4)
    assert blobs.dtype == np.float32
    assert magnets.shape == (19, 4)
    assert magnets.dtype == np.float32


def test_droplet_tear_off_and_coalescence_lifecycle():
    """Verify that droplets detach on audio/periodic excitation and subsequently re-attach."""
    sim = FluidSimulation(seed=42, preset="club")
    analyzer = AudioAnalyzer()
    audio = generate_synthetic_audio("kick120", duration_sec=3.0)

    hop_size = 512
    dt_frame = 1.0 / 60.0

    detached_history = []
    coalescence_observed = False
    prev_detached = set(np.where(sim.detached)[0])

    for i in range(0, len(audio) - hop_size, hop_size):
        chunk = audio[i : i + hop_size]
        feat = analyzer.process_hop(chunk)
        sim.update_choreography(feat, dt_frame)

        curr_detached = set(np.where(sim.detached)[0])
        detached_history.append(len(curr_detached))

        # Check if any droplet that was detached has successfully coalesced back (detached -> attached)
        re_attached = prev_detached - curr_detached
        if len(re_attached) > 0:
            coalescence_observed = True

        prev_detached = curr_detached

    # Must have active detached droplets during simulation
    assert max(detached_history) > 0, "No droplets were ever detached"
    # Must have observed coalescence (re-attaching back to the mother body)
    assert coalescence_observed, "No droplet re-attachment (coalescence) was observed during 3s kick track"


def test_boundary_envelope_and_core_anchoring():
    """Verify that the fluid core remains centered and all droplet envelopes stay well inside window."""
    sim = FluidSimulation(seed=99, preset="club")
    analyzer = AudioAnalyzer()
    audio = generate_synthetic_audio("full_mix", duration_sec=5.0)

    hop_size = 512
    dt_frame = 1.0 / 60.0

    for i in range(0, len(audio) - hop_size, hop_size):
        chunk = audio[i : i + hop_size]
        feat = analyzer.process_hop(chunk)
        sim.update_choreography(feat, dt_frame)

        # 1. Mother puddle center of mass must remain stably anchored near (0, 0)
        p_core = np.mean(sim.pos[:sim.n_core], axis=0)
        core_offset = np.linalg.norm(p_core)
        assert core_offset < 0.20, f"Mother puddle drifted too far: offset={core_offset:.4f}"

        # 2. Maximum droplet position center must never reach 0.80
        pos_dist = np.linalg.norm(sim.pos, axis=1)
        assert np.all(pos_dist < 0.80), f"Droplet center exceeded 0.80: max={np.max(pos_dist):.4f}"

        # 3. Outer potential reach (r_center + r * support_scale) must remain < 0.86 (window edge is 1.0)
        envelope = pos_dist + sim.r * sim.support_scale
        assert np.all(envelope < 0.86), f"Droplet metaball envelope reached window perimeter: max={np.max(envelope):.4f}"
