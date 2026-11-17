# Technical Architecture & Engineering Decisions

## 1. Wayland vs X11 Windowing (`QT_QPA_PLATFORM=xcb`)
- **Context**: On Ubuntu GNOME running Wayland, native Wayland clients cannot place themselves at absolute screen positions, enforce always-on-top, stay on all workspaces, or manipulate input click-through masks without special compositor extensions (GNOME explicitly refuses to implement `wlr-layer-shell`).
- **Decision**: By default, force `QT_QPA_PLATFORM=xcb` (using XWayland). This gives full EWMH support (`_NET_WM_STATE_STICKY`, `_NET_WM_STATE_ABOVE`, `_NET_WM_STATE_SKIP_TASKBAR`, `_NET_WM_WINDOW_TYPE_UTILITY`) and reliable click-through shaping via XShape. If the user explicitly sets `--wayland-native`, we allow native Wayland with clear logging about GNOME limitations.

## 2. Per-Pixel Alpha & OpenGL FBO Binding
- **Context**: In Qt6 `QOpenGLWidget`, rendering happens into an offscreen framebuffer managed by Qt, NOT FBO 0.
- **Decision**: When using modern OpenGL via ModernGL or PyOpenGL inside `paintGL()`, we detect and bind Qt's framebuffer (`ctx.detect_framebuffer()`) rather than default screen FBO. Furthermore, `QSurfaceFormat.setDefaultFormat` is called before `QApplication` instantiation with 8-bit alpha buffer, Core Profile 3.3, and `Qt.WA_TranslucentBackground` set on the window. Output color from `ferro.frag` is strictly premultiplied alpha: `rgb = color * alpha`, `0.0 <= rgb <= alpha <= 1.0`.

## 3. Dynamic Click-Through via XShape vs Qt Window Flags
- **Context**: Calling `setWindowFlag(Qt.WindowTransparentForInput, bool)` dynamically at runtime in Qt6 destroys and recreates the underlying X11 window (`winId()`), dropping EWMH states and causing desktop flicker.
- **Decision**: In `x11.py`, we implement input mask shaping via X11 `XShapeCombineRectangles(ShapeInput)` using `python-xlib` (or `libXext.so.6`). In LOCKED mode, an empty input region makes the window 100% click-through without recreating the native window. In EDIT mode, the input region is restored to the full window rectangle. We also listen to `QEvent.WinIdChange` / `showEvent` as a defense-in-depth fallback.

## 4. Audio Capture: `parec` / `pw-record` with Fault-Tolerant Fallback
- **Context**: System audio must be captured from the default sink monitor, not microphone. Systems may have PipeWire (`pipewire-pulse`) or PulseAudio, or might temporarily lack `parec` or sink devices.
- **Decision**: Query the default sink monitor source (`pactl get-default-sink` + `.monitor` or `@DEFAULT_MONITOR@`). Spawn `parec` (or `pw-record` fallback). Run a `pactl subscribe` watcher thread to dynamically switch sources when default sink changes. If capture fails or no sound server is running, log a structured warning, use exponential backoff, and feed zeroed audio buffers so the fluid smoothly transitions to idle breathing without crashing.

## 5. DSP Thread Safety & Zero-Heap-Churn
- **Context**: High-frequency audio analysis (STFT every ~10 ms) running alongside a 60 FPS GL render loop can cause lock contention and garbage collection pauses.
- **Decision**: The audio capture and analysis pipeline runs entirely on a dedicated thread, mutating preallocated NumPy arrays in-place. It publishes an immutable dataclass `Features` to the GUI thread via atomic reference swap. The GUI thread reads this snapshot synchronously at frame start to step physics and update uniforms.

## 6. Physics: 240 Hz Substepping & Analytic Forces
- **Context**: Variable frame rates or desktop stutter can cause Euler integration instabilities or explosive droplet collisions.
- **Decision**: Fluid simulation uses fixed 240 Hz substeps (`dt = 1/240 s`) clamped at max 0.1 s accumulated time. 64 droplets (6 cores, 22 satellites, 36 mist) interact with 19 electromagnets (center, inner ring, outer ring) plus pairwise cohesion, core repulsion, curl-noise drift, and 2nd-order underdamped spring ODEs for droplet radii and Rosensweig spike envelopes.

## 7. Rendering: Fullscreen Analytic Shader with 2.5D Meniscus & HDR Environment
- **Context**: True 3D volume fluid simulations are too heavy for a lightweight desktop widget (< 2 ms/frame budget). Flat 2D circles look artificial.
- **Decision**: Evaluate an analytic polynomial metaball field with analytic gradient in GLSL 330. Add hexagonal Rosensweig spike cone displacement modulated by local magnetic field and audio spike envelope. Derive 2.5D meniscus dome heights and surface normals analytically from the field gradient. Shade with procedural studio HDR environment maps (overhead softbox, rim strips, intense pinpoint specular glints, and studio floor cyclorama bounce for black wallpaper legibility). Output premultiplied alpha with soft drop shadows.
