"""Unit and visual verification tests for OpenGL shader rendering."""

import numpy as np
from PIL import Image

from ferrowidget.config import LookConfig, PerfConfig
from ferrowidget.physics.fluid import FluidSimulation
from ferrowidget.render.renderer import THEMES, FerroRenderer


def test_renderer_initialization_and_offscreen_render():
    """Verify shader compilation, offscreen render, and image size."""
    renderer = FerroRenderer()
    sim = FluidSimulation(seed=42)

    blobs = sim.get_blobs_uniform_data()
    magnets = sim.get_magnets_uniform_data()

    img = renderer.render_offscreen_image(
        width=256,
        height=256,
        time_sec=1.0,
        blobs_data=blobs,
        magnets_data=magnets,
        spike_amount=0.5,
    )

    assert isinstance(img, Image.Image)
    assert img.size == (256, 256)
    assert img.mode == "RGBA"


def test_alpha_boundary_and_premultiplied_invariants():
    """Verify corner transparency, non-zero fluid center, and premultiplied invariant (rgb <= alpha)."""
    renderer = FerroRenderer()
    sim = FluidSimulation(seed=42)

    blobs = sim.get_blobs_uniform_data()
    magnets = sim.get_magnets_uniform_data()

    img = renderer.render_offscreen_image(
        width=256,
        height=256,
        time_sec=1.0,
        blobs_data=blobs,
        magnets_data=magnets,
        spike_amount=0.5,
    )

    arr = np.array(img, dtype=np.float32) / 255.0
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]

    # Corner pixels must be completely transparent
    corner_alphas = [a[0, 0], a[0, -1], a[-1, 0], a[-1, -1]]
    for ca in corner_alphas:
        assert ca == 0.0, f"Corner alpha expected 0.0, got {ca}"

    # Entire window perimeter edges must be strictly transparent (no square boundary clipping)
    assert np.all(a[0, :] == 0.0), f"Top edge has non-zero alpha: max={a[0, :].max()}"
    assert np.all(a[-1, :] == 0.0), f"Bottom edge has non-zero alpha: max={a[-1, :].max()}"
    assert np.all(a[:, 0] == 0.0), f"Left edge has non-zero alpha: max={a[:, 0].max()}"
    assert np.all(a[:, -1] == 0.0), f"Right edge has non-zero alpha: max={a[:, -1].max()}"

    # Center pixels must contain fluid
    center_alpha = a[128, 128]
    assert center_alpha > 0.5, f"Center alpha expected > 0.5, got {center_alpha}"

    # Premultiplied invariant check: rgb <= alpha + tolerance for dither
    # With blue noise/hash dither +/- 0.5/255 ~= 0.002
    tolerance = 0.015
    assert (r <= a + tolerance).all(), "Red channel exceeds alpha"
    assert (g <= a + tolerance).all(), "Green channel exceeds alpha"
    assert (b <= a + tolerance).all(), "Blue channel exceeds alpha"


def test_all_themes_render():
    """Verify that ink, mercury, oilslick, and neon all render without GL errors."""
    renderer = FerroRenderer()
    sim = FluidSimulation(seed=42)
    blobs = sim.get_blobs_uniform_data()
    magnets = sim.get_magnets_uniform_data()

    for theme_name in THEMES.keys():
        look = LookConfig(theme=theme_name)
        img = renderer.render_offscreen_image(
            width=128,
            height=128,
            time_sec=0.5,
            blobs_data=blobs,
            magnets_data=magnets,
            spike_amount=0.8,
            look_cfg=look,
        )
        assert img.size == (128, 128)
        arr = np.array(img)
        assert arr[:, :, 3].max() > 0, f"Theme {theme_name} rendered empty image"


def test_raymarch_mode_render():
    """Verify stretch raymarch mode executes and renders valid output."""
    renderer = FerroRenderer()
    sim = FluidSimulation(seed=42)
    blobs = sim.get_blobs_uniform_data()
    magnets = sim.get_magnets_uniform_data()
    perf = PerfConfig(mode="raymarch")

    img = renderer.render_offscreen_image(
        width=128,
        height=128,
        time_sec=0.5,
        blobs_data=blobs,
        magnets_data=magnets,
        spike_amount=0.8,
        perf_cfg=perf,
    )
    assert img.size == (128, 128)
    arr = np.array(img)
    assert arr[:, :, 3].max() > 0
