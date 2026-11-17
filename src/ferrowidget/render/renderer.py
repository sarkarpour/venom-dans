"""ModernGL-based photorealistic ferrofluid renderer with theme and contact-sheet support."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import moderngl
import numpy as np
from PIL import Image, ImageDraw

from ferrowidget.config import LookConfig, PerfConfig

logger = logging.getLogger(__name__)

SHADER_DIR = Path(__file__).parent / "shaders"

# Theme parameter presets
THEMES = {
    "ink": {
        "f0": 0.065,
        "body_color": (0.01, 0.012, 0.016),
        "rim_color": (0.75, 0.80, 0.85),
        "rim_gain": 0.65,
        "glint_gain": 1.0,
        "shadow_alpha": 0.22,
        "iridescence": 0.0,
    },
    "mercury": {
        "f0": 0.92,
        "body_color": (0.80, 0.82, 0.85),
        "rim_color": (0.95, 0.95, 1.0),
        "rim_gain": 0.85,
        "glint_gain": 1.2,
        "shadow_alpha": 0.35,
        "iridescence": 0.0,
    },
    "oilslick": {
        "f0": 0.065,
        "body_color": (0.015, 0.015, 0.02),
        "rim_color": (0.80, 0.70, 0.95),
        "rim_gain": 0.75,
        "glint_gain": 1.0,
        "shadow_alpha": 0.22,
        "iridescence": 0.75,
    },
    "neon": {
        "f0": 0.08,
        "body_color": (0.008, 0.010, 0.016),
        "rim_color": (0.0, 0.88, 1.0),
        "rim_gain": 1.65,
        "glint_gain": 1.25,
        "shadow_alpha": 0.25,
        "iridescence": 0.0,
    },
}


class FerroRenderer:
    """Manages GL shaders, uniform binding, offscreen FBOs, and frame dumping."""

    def __init__(self, ctx: Optional[moderngl.Context] = None):
        if ctx is None:
            self.ctx = moderngl.create_standalone_context()
        else:
            self.ctx = ctx

        # Load shader code
        vert_code = (SHADER_DIR / "ferro.vert").read_text()
        frag_code = (SHADER_DIR / "ferro.frag").read_text()
        self.program = self.ctx.program(vertex_shader=vert_code, fragment_shader=frag_code)

        # Fullscreen quad (2 triangles)
        # Positions: [-1, -1], [1, -1], [-1, 1], [-1, 1], [1, -1], [1, 1]
        quad_verts = np.array(
            [
                -1.0, -1.0,
                 1.0, -1.0,
                -1.0,  1.0,
                -1.0,  1.0,
                 1.0, -1.0,
                 1.0,  1.0,
            ],
            dtype=np.float32,
        )
        self.vbo = self.ctx.buffer(quad_verts.tobytes())
        self.vao = self.ctx.vertex_array(self.program, [(self.vbo, "2f", "inPosition")])

        # Cached offscreen FBO for headless rendering
        self._fbo: Optional[moderngl.Framebuffer] = None
        self._fbo_size: Tuple[int, int] = (0, 0)

    def render_frame(
        self,
        width: int,
        height: int,
        time_sec: float,
        blobs_data: np.ndarray,      # (64, 4)
        magnets_data: np.ndarray,    # (19, 4)
        spike_amount: float,
        edit_mode: bool = False,
        debug_bg: int = 0,
        look_cfg: Optional[LookConfig] = None,
        perf_cfg: Optional[PerfConfig] = None,
        target_fbo: Optional[moderngl.Framebuffer] = None,
    ) -> None:
        """Bind uniforms, clear target FBO to (0,0,0,0) and render quad."""
        if target_fbo is not None:
            target_fbo.use()
        self.ctx.viewport = (0, 0, width, height)
        self.ctx.clear(0.0, 0.0, 0.0, 0.0)

        def set_uniform(name: str, val):
            if name in self.program:
                self.program[name].value = val

        set_uniform("uResolution", (float(width), float(height)))
        set_uniform("uTime", float(time_sec))
        set_uniform("uBlobCount", int(len(blobs_data)))
        if "uBlobs" in self.program:
            self.program["uBlobs"].write(blobs_data.astype(np.float32).tobytes())
        if "uMagnets" in self.program:
            self.program["uMagnets"].write(magnets_data.astype(np.float32).tobytes())
        set_uniform("uSpike", float(spike_amount))
        set_uniform("uEnvRot", float((time_sec * 0.12) % (2.0 * np.pi)))
        set_uniform("uEditMode", 1.0 if edit_mode else 0.0)
        set_uniform("uDebugBg", int(debug_bg))

        # Perf mode: 0 = heightfield, 1 = raymarch
        mode_idx = 1 if (perf_cfg and perf_cfg.mode == "raymarch") else 0
        set_uniform("uRenderMode", mode_idx)

        # Theme uniforms
        theme_name = look_cfg.theme if look_cfg else "ink"
        theme_params = THEMES.get(theme_name, THEMES["ink"])

        rim_mult = look_cfg.rim if look_cfg else 0.65
        glints_mult = look_cfg.glints if look_cfg else 1.0
        shadow_mult = look_cfg.shadow if look_cfg else 0.22
        iri_mult = look_cfg.iridescence if look_cfg else 0.0

        set_uniform("uF0", float(theme_params["f0"]))
        set_uniform("uBodyColor", theme_params["body_color"])
        set_uniform("uRimColor", theme_params["rim_color"])
        set_uniform("uRimGain", float(theme_params["rim_gain"] * rim_mult))
        set_uniform("uGlintGain", float(theme_params["glint_gain"] * glints_mult))
        set_uniform("uShadowAlpha", float(theme_params["shadow_alpha"] * shadow_mult))
        set_uniform("uIridescence", float(max(theme_params["iridescence"], iri_mult)))

        # Render fullscreen quad
        self.vao.render(moderngl.TRIANGLES)

    def render_offscreen_image(
        self,
        width: int,
        height: int,
        time_sec: float,
        blobs_data: np.ndarray,
        magnets_data: np.ndarray,
        spike_amount: float,
        edit_mode: bool = False,
        debug_bg: int = 0,
        look_cfg: Optional[LookConfig] = None,
        perf_cfg: Optional[PerfConfig] = None,
    ) -> Image.Image:
        """Render to an offscreen RGBA texture and return a PIL Image."""
        if self._fbo is None or self._fbo_size != (width, height):
            if self._fbo is not None:
                self._fbo.release()
            tex = self.ctx.texture((width, height), 4)
            self._fbo = self.ctx.framebuffer(color_attachments=[tex])
            self._fbo_size = (width, height)

        self.render_frame(
            width=width,
            height=height,
            time_sec=time_sec,
            blobs_data=blobs_data,
            magnets_data=magnets_data,
            spike_amount=spike_amount,
            edit_mode=edit_mode,
            debug_bg=debug_bg,
            look_cfg=look_cfg,
            perf_cfg=perf_cfg,
            target_fbo=self._fbo,
        )

        raw_data = self._fbo.read(components=4)
        # OpenGL textures are vertically flipped relative to PIL image coordinates
        img = Image.frombytes("RGBA", (width, height), raw_data).transpose(Image.FLIP_TOP_BOTTOM)
        return img


def create_contact_sheet(
    moments: List[Tuple[str, Image.Image]],
    backgrounds: List[str] = ["white", "mid-grey", "pure-black", "busy-wallpaper-gradient"],
    cell_size: int = 256,
) -> Image.Image:
    """Composite a multi-background, multi-moment contact sheet.

    Rows: Background types (white, mid-grey, pure-black, gradient)
    Columns: Key moments (idle, steady_bass, kick_+0ms, kick_+50ms, kick_+120ms, kick_+250ms, full_mix, max_spikes)
    """
    n_cols = len(moments)
    n_rows = len(backgrounds)

    header_height = 40
    col_header_height = 30
    row_label_width = 160
    padding = 10

    total_w = row_label_width + n_cols * (cell_size + padding) + padding
    total_h = header_height + col_header_height + n_rows * (cell_size + padding) + padding

    sheet = Image.new("RGB", (total_w, total_h), (25, 27, 30))
    draw = ImageDraw.Draw(sheet)

    # Title header
    draw.text((padding, 12), "FerroWidget Multi-Background & Dynamics Contact Sheet", fill=(240, 240, 245))

    # Column titles (moments)
    for c, (moment_name, _) in enumerate(moments):
        x = row_label_width + c * (cell_size + padding)
        y = header_height + 6
        draw.text((x + 10, y), moment_name, fill=(200, 210, 225))

    # Pre-render background patterns
    bg_images = {}
    for bg in backgrounds:
        if bg == "white":
            bg_img = Image.new("RGBA", (cell_size, cell_size), (255, 255, 255, 255))
        elif bg == "mid-grey":
            bg_img = Image.new("RGBA", (cell_size, cell_size), (128, 128, 128, 255))
        elif bg == "pure-black":
            bg_img = Image.new("RGBA", (cell_size, cell_size), (0, 0, 0, 255))
        else:  # "busy-wallpaper-gradient"
            # High-contrast vibrant gradient pattern
            arr = np.zeros((cell_size, cell_size, 4), dtype=np.uint8)
            y_coords, x_coords = np.mgrid[0:cell_size, 0:cell_size]
            arr[:, :, 0] = (20 + 200 * (x_coords / cell_size)).astype(np.uint8)
            arr[:, :, 1] = (40 + 160 * (y_coords / cell_size)).astype(np.uint8)
            arr[:, :, 2] = (180 * np.sin(x_coords * 0.05) + 60).astype(np.uint8)
            arr[:, :, 3] = 255
            bg_img = Image.fromarray(arr, "RGBA")
        bg_images[bg] = bg_img

    # Grid composition
    for r, bg in enumerate(backgrounds):
        y = header_height + col_header_height + r * (cell_size + padding)
        # Row label
        draw.text((padding + 8, y + cell_size // 2 - 10), f"Bg: {bg}", fill=(210, 215, 225))

        for c, (_, fluid_img) in enumerate(moments):
            x = row_label_width + c * (cell_size + padding)
            resized_fluid = fluid_img.resize((cell_size, cell_size), Image.Resampling.LANCZOS)

            # Alpha composite premultiplied or standard RGBA
            cell_bg = bg_images[bg].copy()
            cell_bg.alpha_composite(resized_fluid)

            sheet.paste(cell_bg.convert("RGB"), (x, y))

    return sheet
