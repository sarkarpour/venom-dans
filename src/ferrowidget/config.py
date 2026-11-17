"""Configuration dataclasses, validation, TOML loading/saving, and hot-reload."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore



DEFAULT_CONFIG_PATH = Path.home() / ".config" / "ferrowidget" / "config.toml"

CONFIG_TEMPLATE = """# FerroWidget Configuration File
# Real-time photorealistic ferrofluid desktop audio visualizer

[window]
# Top-left position on screen (-1 for automatic placement via anchor/margin)
x = {x}
y = {y}
# Widget square dimension in pixels (128 - 1200)
size = {size}
# Monitor selection: "primary" or monitor index name
monitor = "{monitor}"
# Stacking layer: "top", "normal", "bottom"
layer = "{layer}"
# Locked mode: true = click-through desktop overlay, false = editable/draggable
locked = {locked}
# Window opacity (0.1 - 1.0)
opacity = {opacity}
# Automatic anchor point when x/y are -1: "top-left", "top-right", "bottom-left", "bottom-right", "center"
anchor = "{anchor}"
# Margin from screen edges when anchored (pixels)
margin = {margin}

[audio]
# Sound source: "auto" (default monitor sink) or specific Pulse/PipeWire source name
source = "{source}"
# Audio sensitivity multiplier (0.1 - 10.0)
sensitivity = {sensitivity}
# Latency compensation delay in milliseconds (0 - 500)
visual_delay_ms = {visual_delay_ms}
# Adaptive Gain Control enabled
agc = {agc}

[fluid]
# Movement preset: "calm", "club", "cinematic"
preset = "{preset}"
# Number of simulated droplets (default: 64)
droplets = {droplets}
# Viscosity drag factor (0.1 - 5.0)
viscosity = {viscosity}
# Magnetic attraction multiplier (0.1 - 5.0)
magnet_gain = {magnet_gain}
# Kick radial expansion impulse multiplier (0.1 - 5.0)
kick_impulse = {kick_impulse}
# Rosensweig spike height multiplier (0.0 - 5.0)
spike_amount = {spike_amount}
# Enable gentle breathing curl-noise drift during silence/quiet passages
idle_breathing = {idle_breathing}

[look]
# Visual theme: "ink", "mercury", "oilslick", "neon"
theme = "{theme}"
# Outer rim light reflection gain (0.0 - 2.0)
rim = {rim}
# Specular glint intensity multiplier (0.0 - 3.0)
glints = {glints}
# Drop shadow opacity (0.0 - 1.0)
shadow = {shadow}
# Thin-film iridescence factor (0.0 - 1.0)
iridescence = {iridescence}

[perf]
# Active rendering frame rate limit (15 - 240)
fps_cap = {fps_cap}
# Idle rendering frame rate during extended silence (5 - 60)
idle_fps = {idle_fps}
# Internal FBO resolution scale multiplier (0.5 - 2.0)
render_scale = {render_scale}
# Render pipeline mode: "heightfield" (2.5D meniscus) or "raymarch" (3D SDF)
mode = "{mode}"
"""


@dataclass
class WindowConfig:
    x: int = -1
    y: int = -1
    size: int = 420
    monitor: str = "primary"
    layer: str = "top"
    locked: bool = True
    opacity: float = 1.0
    anchor: str = "bottom-right"
    margin: int = 40

    def validate(self) -> None:
        try:
            self.size = max(128, min(1200, int(self.size)))
        except (ValueError, TypeError):
            self.size = 420
        if self.layer not in ("top", "normal", "bottom"):
            self.layer = "top"
        if self.anchor not in ("top-left", "top-right", "bottom-left", "bottom-right", "center"):
            self.anchor = "bottom-right"
        try:
            self.margin = max(0, min(500, int(self.margin)))
        except (ValueError, TypeError):
            self.margin = 40
        try:
            self.opacity = max(0.1, min(1.0, float(self.opacity)))
        except (ValueError, TypeError):
            self.opacity = 1.0


@dataclass
class AudioConfig:
    source: str = "auto"
    sensitivity: float = 1.0
    visual_delay_ms: int = 0
    agc: bool = True

    def validate(self) -> None:
        try:
            self.sensitivity = max(0.1, min(10.0, float(self.sensitivity)))
        except (ValueError, TypeError):
            self.sensitivity = 1.0
        try:
            self.visual_delay_ms = max(0, min(500, int(self.visual_delay_ms)))
        except (ValueError, TypeError):
            self.visual_delay_ms = 0


@dataclass
class FluidConfig:
    preset: str = "club"
    droplets: int = 64
    viscosity: float = 1.0
    magnet_gain: float = 1.0
    kick_impulse: float = 1.0
    spike_amount: float = 1.0
    idle_breathing: bool = True

    def validate(self) -> None:
        if self.preset not in ("calm", "club", "cinematic"):
            self.preset = "club"
        try:
            self.droplets = max(16, min(128, int(self.droplets)))
        except (ValueError, TypeError):
            self.droplets = 64
        try:
            self.viscosity = max(0.1, min(5.0, float(self.viscosity)))
        except (ValueError, TypeError):
            self.viscosity = 1.0
        try:
            self.magnet_gain = max(0.1, min(5.0, float(self.magnet_gain)))
        except (ValueError, TypeError):
            self.magnet_gain = 1.0
        try:
            self.kick_impulse = max(0.1, min(5.0, float(self.kick_impulse)))
        except (ValueError, TypeError):
            self.kick_impulse = 1.0
        try:
            self.spike_amount = max(0.0, min(5.0, float(self.spike_amount)))
        except (ValueError, TypeError):
            self.spike_amount = 1.0


@dataclass
class LookConfig:
    theme: str = "ink"
    rim: float = 0.65
    glints: float = 1.0
    shadow: float = 0.22
    iridescence: float = 0.0

    def validate(self) -> None:
        if self.theme not in ("ink", "mercury", "oilslick", "neon"):
            self.theme = "ink"
        try:
            self.rim = max(0.0, min(2.0, float(self.rim)))
        except (ValueError, TypeError):
            self.rim = 0.65
        try:
            self.glints = max(0.0, min(3.0, float(self.glints)))
        except (ValueError, TypeError):
            self.glints = 1.0
        try:
            self.shadow = max(0.0, min(1.0, float(self.shadow)))
        except (ValueError, TypeError):
            self.shadow = 0.22
        try:
            self.iridescence = max(0.0, min(1.0, float(self.iridescence)))
        except (ValueError, TypeError):
            self.iridescence = 0.0


@dataclass
class PerfConfig:
    fps_cap: int = 60
    idle_fps: int = 15
    render_scale: float = 1.0
    mode: str = "heightfield"

    def validate(self) -> None:
        try:
            self.fps_cap = max(15, min(240, int(self.fps_cap)))
        except (ValueError, TypeError):
            self.fps_cap = 60
        try:
            self.idle_fps = max(5, min(60, int(self.idle_fps)))
        except (ValueError, TypeError):
            self.idle_fps = 15
        try:
            self.render_scale = max(0.5, min(2.0, float(self.render_scale)))
        except (ValueError, TypeError):
            self.render_scale = 1.0
        if self.mode not in ("heightfield", "raymarch"):
            self.mode = "heightfield"


@dataclass
class AppConfig:
    window: WindowConfig = field(default_factory=WindowConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    fluid: FluidConfig = field(default_factory=FluidConfig)
    look: LookConfig = field(default_factory=LookConfig)
    perf: PerfConfig = field(default_factory=PerfConfig)

    def validate(self) -> None:
        self.window.validate()
        self.audio.validate()
        self.fluid.validate()
        self.look.validate()
        self.perf.validate()

    @classmethod
    def load(cls, path: Optional[Path] = None) -> AppConfig:
        config_path = path or DEFAULT_CONFIG_PATH
        if not config_path.exists():
            cfg = cls()
            cfg.save(config_path)
            return cfg

        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            cfg = cls()
            return cfg

        cfg = cls(
            window=WindowConfig(**{k: v for k, v in data.get("window", {}).items() if hasattr(WindowConfig, k)}),
            audio=AudioConfig(**{k: v for k, v in data.get("audio", {}).items() if hasattr(AudioConfig, k)}),
            fluid=FluidConfig(**{k: v for k, v in data.get("fluid", {}).items() if hasattr(FluidConfig, k)}),
            look=LookConfig(**{k: v for k, v in data.get("look", {}).items() if hasattr(LookConfig, k)}),
            perf=PerfConfig(**{k: v for k, v in data.get("perf", {}).items() if hasattr(PerfConfig, k)}),
        )
        cfg.validate()
        return cfg

    def save(self, path: Optional[Path] = None) -> None:
        config_path = path or DEFAULT_CONFIG_PATH
        config_path.parent.mkdir(parents=True, exist_ok=True)
        self.validate()

        content = CONFIG_TEMPLATE.format(
            x=self.window.x,
            y=self.window.y,
            size=self.window.size,
            monitor=self.window.monitor,
            layer=self.window.layer,
            locked=str(self.window.locked).lower(),
            opacity=self.window.opacity,
            anchor=self.window.anchor,
            margin=self.window.margin,
            source=self.audio.source,
            sensitivity=self.audio.sensitivity,
            visual_delay_ms=self.audio.visual_delay_ms,
            agc=str(self.audio.agc).lower(),
            preset=self.fluid.preset,
            droplets=self.fluid.droplets,
            viscosity=self.fluid.viscosity,
            magnet_gain=self.fluid.magnet_gain,
            kick_impulse=self.fluid.kick_impulse,
            spike_amount=self.fluid.spike_amount,
            idle_breathing=str(self.fluid.idle_breathing).lower(),
            theme=self.look.theme,
            rim=self.look.rim,
            glints=self.look.glints,
            shadow=self.look.shadow,
            iridescence=self.look.iridescence,
            fps_cap=self.perf.fps_cap,
            idle_fps=self.perf.idle_fps,
            render_scale=self.perf.render_scale,
            mode=self.perf.mode,
        )
        tmp_path = config_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, config_path)
