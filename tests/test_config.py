"""Unit tests for configuration loading, validation, clamping, and persistence."""

import tempfile
from pathlib import Path

from ferrowidget.config import AppConfig


def test_default_config_validation():
    """Verify default config satisfies all validation constraints."""
    cfg = AppConfig()
    cfg.validate()

    assert cfg.window.size == 420
    assert cfg.window.layer == "top"
    assert cfg.window.locked is True
    assert cfg.audio.source == "auto"
    assert cfg.fluid.preset == "club"
    assert cfg.look.theme == "ink"
    assert cfg.perf.fps_cap == 60


def test_clamping_out_of_bounds_values():
    """Verify out-of-bounds values are safely clamped on validation."""
    cfg = AppConfig()
    cfg.window.size = 99999
    cfg.window.layer = "invalid_layer"
    cfg.window.margin = -50
    cfg.audio.sensitivity = -10.0
    cfg.audio.visual_delay_ms = 9999
    cfg.fluid.droplets = 500
    cfg.fluid.viscosity = 100.0
    cfg.fluid.preset = "unknown_preset"
    cfg.look.theme = "nonexistent"
    cfg.perf.fps_cap = 1000

    cfg.validate()

    assert cfg.window.size == 1200
    assert cfg.window.layer == "top"
    assert cfg.window.margin == 0
    assert cfg.audio.sensitivity == 0.1
    assert cfg.audio.visual_delay_ms == 500
    assert cfg.fluid.droplets == 128
    assert cfg.fluid.viscosity == 5.0
    assert cfg.fluid.preset == "club"
    assert cfg.look.theme == "ink"
    assert cfg.perf.fps_cap == 240


def test_save_and_reload_persistence():
    """Verify saving to custom path and reloading preserves custom values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "config.toml"
        cfg = AppConfig()
        cfg.window.size = 512
        cfg.look.theme = "mercury"
        cfg.fluid.preset = "cinematic"
        cfg.save(tmp_path)

        assert tmp_path.exists()
        loaded = AppConfig.load(tmp_path)

        assert loaded.window.size == 512
        assert loaded.look.theme == "mercury"
        assert loaded.fluid.preset == "cinematic"
