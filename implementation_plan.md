# FerroWidget Implementation Plan

## 1. Overview
FerroWidget is a standalone Ubuntu desktop widget that renders a photorealistic, glossy black ferrofluid (droplets that merge, stretch, pinch off, and sprout sharp magnetic spikes on bass hits) floating directly on the desktop with a fully transparent background. It reacts to system audio output (`<default_sink>.monitor`) with <= 60 ms end-to-end latency.

## 2. Architecture & Modules
- **`src/ferrowidget/config.py`**: Typed dataclasses (`WindowConfig`, `AudioConfig`, `FluidConfig`, `LookConfig`, `PerfConfig`), TOML load/save with comments and validation/clamping, and `QFileSystemWatcher` live hot-reload.
- **`src/ferrowidget/x11.py`**: EWMH hints (`_NET_WM_STATE_STICKY`, `_NET_WM_STATE_ABOVE`, `_NET_WM_STATE_SKIP_TASKBAR`, `_NET_WM_STATE_SKIP_PAGER`, `_NET_WM_WINDOW_TYPE_UTILITY`) and `XShapeCombineRectangles` input mask management for click-through without window recreation.
- **`src/ferrowidget/ipc.py`**: QLocalServer / QLocalSocket JSON-line protocol over `$XDG_RUNTIME_DIR/ferrowidget.sock`.
- **`src/ferrowidget/audio/`**:
  - `synthetic.py`: Deterministic test signal generators (`kick120`, `bass_sweep`, `noise_bursts`, `full_mix`, `silence`).
  - `analysis.py`: Hann STFT, 32 log bands, +3dB/octave pink noise tilt compensation, per-band AGC, spectral flux onset detectors (`kick`, `snare`, `hat`), beat phase tracking, ring buffer delay line, immutable `Features` snapshot.
  - `capture.py`: `parec` / `pw-record` audio capture thread, `pactl subscribe` sink change watcher, exponential backoff, zeroed-frame idle fallback.
- **`src/ferrowidget/physics/fluid.py`**: 64 droplets (6 core, 22 satellite, 36 mist), 19 electromagnets (center, inner ring, outer ring), 240 Hz substeps, pairwise soft cohesion & core repulsion, curl-noise drift, viscous drag, audio impulses, 2nd-order underdamped spring ODEs for radii and spikes, presets (`calm`, `club`, `cinematic`).
- **`src/ferrowidget/render/`**:
  - `shaders/ferro.vert`, `shaders/ferro.frag`: Single fullscreen quad, analytic metaball potential & gradient, domain-warped hexagonal Rosensweig spike displacement, analytic signed-distance anti-aliasing, 2.5D meniscus height-field normals with capillary ripples, procedural HDR studio reflections with softboxes and crisp pinpoint glints, studio floor bounce for dark wallpapers, thin-film iridescence, soft drop shadows, premultiplied alpha. Also supports `raymarch` mode for 3D sphere-tracing.
  - `renderer.py`: OpenGL context management, uniform buffer packing, render_scale FBO, offscreen headless renderer and contact-sheet compositor.
- **`src/ferrowidget/window.py`**: Transparent frameless Qt6 window, LOCKED vs EDIT mode handling, geometry persistence, tray icon with procedural ferrofluid icon.
- **`src/ferrowidget/app.py`**: Application lifecycle, clean SIGINT/SIGTERM handlers, `--exit-after` timer, child process cleanup.
- **`src/ferrowidget/cli.py`**: Subcommands: `run`, `ctl`, `doctor`, `dump-frame`, `install-autostart`.

## 3. Step-by-Step Implementation & Verification Phases
- **Phase 0: Recon & Plan**: Check environment, setup git, venv, task.md, implementation_plan.md, docs/DECISIONS.md.
- **Phase 1: Skeleton, Doctor, Config, IPC, Window**:
  - Build `pyproject.toml`, `config.py`, `x11.py`, `ipc.py`, `window.py`, `app.py`, `cli.py`.
  - Implement `doctor` checks with actionable apt package recommendations.
  - Test `ferrowidget doctor`, test `config.py` loading/saving/validation, test IPC and window creation with `--exit-after 3`.
- **Phase 2: Audio Capture, DSP & Synthetic Signals**:
  - Build `synthetic.py`, `analysis.py`, `capture.py`.
  - Write `tests/test_dsp.py`: verify FFT band accuracy, 120 BPM onset detection within +/-1 hop, AGC invariance across +/-30 dB gain, hop latency < 1 ms.
- **Phase 3: Physics & Choreography**:
  - Build `physics/fluid.py`: 64 droplets, 19 magnets, forces, spring ODEs, presets.
  - Write `tests/test_physics.py`: verify determinism with seeded RNG, zero NaNs/Infs, bounded kinetic energy over 10 simulated minutes.
- **Phase 4: Photorealistic Shader & Offscreen Contact Sheets**:
  - Build `shaders/ferro.vert`, `shaders/ferro.frag`, `renderer.py`.
  - Write `tests/test_render.py`: verify alpha boundaries, premultiplied alpha invariants, theme parameters.
  - Implement `dump-frame --contact-sheet`: generate contact sheets with 4 backgrounds (`white`, `mid-grey`, `pure-black`, `busy-wallpaper-gradient`) and 4 themes (`ink`, `mercury`, `oilslick`, `neon`).
  - Visually inspect images, critique glints, rim lighting, spikes, and tune parameters.
- **Phase 5: Live Desktop Integration, Profiling & Polish**:
  - Verify live execution on desktop, test `ferrowidget ctl` commands (`edit`, `theme`, `preset`, `size`, `status`, `quit`).
  - Verify CPU <= 5% (or document baseline & optimize), memory stability, clean process termination.
- **Phase 6: Packaging, Stretch Features & Final Walkthrough**:
  - Implement raymarching stretch mode, tempo-locked breathing.
  - Build packaging files (`ferrowidget.desktop`, `ferrowidget.service`, `install-autostart`).
  - Create `README.md` and `walkthrough.md` with visual artifacts and benchmark results.
