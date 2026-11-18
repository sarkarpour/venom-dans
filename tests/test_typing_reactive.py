"""Unit and integration tests for typing reactive mode and microphone toggle."""

import time

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from ferrowidget.config import AppConfig
from ferrowidget.physics.fluid import FluidSimulation
from ferrowidget.typing_listener import TypingListener
from ferrowidget.window import FerroWindow


def test_fluid_simulation_typing_impulse():
    """Verify inject_typing_impulse pulses radii, electromagnets and sprouts Rosensweig spikes."""
    sim = FluidSimulation(seed=42)
    initial_spike = sim.spike
    initial_spike_vel = sim.spike_vel

    sim.inject_typing_impulse(strength=1.0)

    # Spike and spike_vel should have experienced positive kick
    assert sim.spike > initial_spike
    assert sim.spike_vel > initial_spike_vel
    assert sim.spike <= 1.8

    # Radii velocities should have positive kinetic kick
    assert np.any(sim.r_vel > 0.0)

    # Electromagnet field should pulse
    assert sim.magnet_str[0] > 0.0

    # Simulate 60 keystrokes during rapid typing and ensure bounded, non-NaN energy
    for _ in range(60):
        sim.inject_typing_impulse(strength=float(np.random.uniform(0.8, 1.2)))
        feat = sim._make_default_features() if hasattr(sim, "_make_default_features") else None
        if feat is not None:
            sim.update_choreography(feat, 1.0 / 60.0)

    assert not np.isnan(sim.spike)
    assert not np.isnan(sim.pos).any()
    assert not np.isnan(sim.vel).any()
    assert np.all(np.abs(sim.pos) <= 1.5)


def test_typing_listener_lifecycle_and_debounce():
    """Verify TypingListener starts, triggers debounced callbacks, and terminates cleanly."""
    counter = 0

    def on_press():
        nonlocal counter
        counter += 1

    listener = TypingListener(on_key_press=on_press)
    listener.start()
    assert listener.is_running

    # First trigger should increment counter
    listener.trigger()
    assert counter == 1

    # Immediate second trigger (<25ms) should be rate-limited by debounce
    listener.trigger()
    assert counter == 1

    # After debounce interval, trigger should increment
    time.sleep(0.04)
    listener.trigger()
    assert counter == 2

    listener.stop()
    assert not listener.is_running


def test_ferro_window_typing_and_mic_toggles():
    """Verify FerroWindow toggles typing reactive and mic modes with UI button parity."""
    _app = QApplication.instance() or QApplication([])

    cfg = AppConfig()
    cfg.audio.typing_reactive = False
    cfg.audio.mic_mode = False

    sim = FluidSimulation()
    win = FerroWindow(
        config=cfg,
        simulation=sim,
        features_provider=lambda: None,
    )

    try:
        # Initial states
        assert win.is_typing_reactive is False
        assert win.is_mic_mode is False
        assert "خاموش" in win.btn_typing.text()
        assert "خاموش" in win.btn_mic.text()

        # Toggle typing reactive ON
        win.toggle_typing_reactive()
        assert win.is_typing_reactive is True
        assert win.config.audio.typing_reactive is True
        assert "فعال" in win.btn_typing.text()

        # Toggle mic mode ON
        win.toggle_mic_mode()
        assert win.is_mic_mode is True
        assert win.config.audio.mic_mode is True
        assert "فعال" in win.btn_mic.text()

        # Test hotkey simulation: Ctrl+Shift+T toggles typing OFF
        event_t = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_T,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        win.keyPressEvent(event_t)
        assert win.is_typing_reactive is False
        assert "خاموش" in win.btn_typing.text()

        # Test hotkey simulation: Ctrl+Shift+M toggles mic OFF
        event_m = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_M,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        win.keyPressEvent(event_m)
        assert win.is_mic_mode is False
        assert "خاموش" in win.btn_mic.text()

        # Test locked mode hiding overlay buttons
        win.set_locked(True)
        assert win.is_locked is True
        assert win.btn_typing.isHidden()
        assert win.btn_mic.isHidden()

        # Test edit mode showing overlay buttons
        win.set_locked(False)
        assert win.is_locked is False
        assert not win.btn_typing.isHidden()
        assert not win.btn_mic.isHidden()

    finally:
        win.cleanup()
        win.close()
