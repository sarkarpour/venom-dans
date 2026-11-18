"""Frameless, transparent OpenGL desktop window with locked/edit modes and system tray."""

from __future__ import annotations

import logging
import sys
import time
from typing import Optional

import moderngl
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QGuiApplication,
    QIcon,
    QMouseEvent,
    QPainter,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QSystemTrayIcon, QWidget

from ferrowidget.audio.analysis import Features
from ferrowidget.config import AppConfig
from ferrowidget.physics.fluid import FluidSimulation
from ferrowidget.render.renderer import THEMES, FerroRenderer
from ferrowidget.typing_listener import TypingListener
from ferrowidget.x11 import apply_ewmh_hints, set_click_through

logger = logging.getLogger(__name__)


def set_windows_click_through(hwnd: int, click_through: bool) -> None:
    """Set WS_EX_TRANSPARENT on Windows to pass mouse events through."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000

        GetWindowLong = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        SetWindowLong = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        GetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int]
        GetWindowLong.restype = ctypes.c_ssize_t
        SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        SetWindowLong.restype = ctypes.c_ssize_t

        style = GetWindowLong(hwnd, GWL_EXSTYLE)
        if click_through:
            SetWindowLong(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
        else:
            SetWindowLong(hwnd, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT)
    except Exception as e:
        logger.debug("Windows click-through error: %s", e)


class _TypingSignalBridge(QObject):
    pulse = Signal()
    hotkey_typing = Signal()
    hotkey_mic = Signal()
    hotkey_edit = Signal()


class FerroControlsOverlay(QWidget):
    """Floating glassmorphism toolbar hosting toggle buttons for typing and mic modes."""

    def __init__(self, owner: "FerroWindow"):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.owner = owner
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_AlwaysStackOnTop, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setObjectName("FerroControlsOverlay")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self.btn_typing = QPushButton("⌨️ تایپ: خاموش", self)
        self.btn_mic = QPushButton("🎤 میکروفن: خاموش", self)
        self.btn_close = QPushButton("✕", self)

        for btn in (self.btn_typing, self.btn_mic, self.btn_close):
            btn.setFocusPolicy(Qt.NoFocus)

        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setToolTip("مخفی کردن دکمه‌ها (از منوی تسک‌بار یا با کلید میانبر قابل بازگشت است)")
        self.btn_close.setStyleSheet(
            "QPushButton { background: rgba(255, 255, 255, 0.08); color: #8a99a8; border: none; border-radius: 11px; font-size: 11px; }"
            "QPushButton:hover { background: rgba(255, 77, 77, 0.7); color: #fff; }"
        )

        self.btn_typing.clicked.connect(self.owner.toggle_typing_reactive)
        self.btn_mic.clicked.connect(self.owner.toggle_mic_mode)
        self.btn_close.clicked.connect(self._on_close_clicked)

        layout.addWidget(self.btn_typing)
        layout.addWidget(self.btn_mic)
        layout.addWidget(self.btn_close)

        self.setStyleSheet(
            "#FerroControlsOverlay { background: rgba(15, 19, 26, 0.92); "
            "border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 18px; }"
        )
        self.adjustSize()
        self.update_states()

    def _on_close_clicked(self) -> None:
        self.hide()
        if hasattr(self.owner, "act_controls") and self.owner.act_controls:
            self.owner.act_controls.setChecked(False)

    def update_states(self) -> None:
        style_off = (
            "QPushButton { background: rgba(255, 255, 255, 0.08); color: #c4d0dc; "
            "border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 13px; "
            "font-size: 11px; font-weight: 500; padding: 4px 10px; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 0.16); color: #fff; border-color: rgba(0, 229, 255, 0.5); }"
        )
        style_on = (
            "QPushButton { background: #00e5ff; color: #05070a; "
            "border: 1px solid #00e5ff; border-radius: 13px; "
            "font-size: 11px; font-weight: 700; padding: 4px 10px; }"
            "QPushButton:hover { background: #33ebff; border-color: #33ebff; }"
        )
        if self.owner.is_typing_reactive:
            self.btn_typing.setStyleSheet(style_on)
            self.btn_typing.setText("⌨️ تایپ: فعال")
            self.btn_typing.setToolTip("حالت حساس به تایپ فعال است (کلیک برای خاموش کردن)")
        else:
            self.btn_typing.setStyleSheet(style_off)
            self.btn_typing.setText("⌨️ تایپ: خاموش")
            self.btn_typing.setToolTip("کلیک برای فعال کردن واکنش فروسیال به تایپ کیبورد")

        if self.owner.is_mic_mode:
            self.btn_mic.setStyleSheet(style_on)
            self.btn_mic.setText("🎤 میکروفن: فعال")
            self.btn_mic.setToolTip("ورودی میکروفن فعال است (کلیک برای بازگشت به صدای سیستم)")
        else:
            self.btn_mic.setStyleSheet(style_off)
            self.btn_mic.setText("🎤 میکروفن: خاموش")
            self.btn_mic.setToolTip("کلیک برای روشن کردن میکروفن و واکنش به صدای محیط")

    def update_position(self) -> None:
        if not self.isVisible():
            return
        w_geo = self.owner.geometry()
        x = w_geo.x() + (w_geo.width() - self.width()) // 2
        y = w_geo.y() + w_geo.height() - self.height() - 10
        self.move(x, y)


class FerroWindow(QOpenGLWidget):
    """Transparent, frameless, click-through desktop overlay rendering photorealistic ferrofluid."""

    def __init__(
        self,
        config: AppConfig,
        simulation: FluidSimulation,
        features_provider,
        debug_bg: int = 0,
        audio_capture=None,
        parent=None,
    ):
        super().__init__(parent)
        self.config = config
        self.sim = simulation
        self.features_provider = features_provider
        self.debug_bg = debug_bg
        self.audio_capture = audio_capture

        # Window flags: Frameless, transparent, bypass window manager decorations
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SubWindow
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_AlwaysStackOnTop, True)

        # In locked mode, widget does not accept focus
        self.setFocusPolicy(Qt.NoFocus)

        # State
        self.is_locked = self.config.window.locked
        self.is_typing_reactive = bool(self.config.audio.typing_reactive)
        self.is_mic_mode = bool(self.config.audio.mic_mode)
        self.last_typing_time = 0.0

        self.renderer: Optional[FerroRenderer] = None
        self.ctx: Optional[moderngl.Context] = None
        self._cached_qt_fbo: Optional[moderngl.Framebuffer] = None
        self._cached_fbo_id: int = -1

        # Dragging state in edit mode
        self._dragging = False
        self._drag_start_pos = QPoint()
        self._drag_window_pos = QPoint()

        # Frame timing
        self.last_frame_time = time.perf_counter()
        self.start_time = time.perf_counter()
        self.frame_count = 0
        self.fps_metric = 0.0
        self._fps_timer = time.perf_counter()

        # Render timer
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.update)
        self._update_timer_interval()

        # Setup initial geometry based on monitor and config
        self._apply_geometry_from_config()

        # Typing listener setup with GUI thread bridge & global hotkeys
        self._typing_bridge = _TypingSignalBridge()
        self._typing_bridge.pulse.connect(self._on_typing_pulse_gui)
        self._typing_bridge.hotkey_typing.connect(self.toggle_typing_reactive)
        self._typing_bridge.hotkey_mic.connect(self.toggle_mic_mode)
        self._typing_bridge.hotkey_edit.connect(lambda: self.set_locked(not self.is_locked))

        self.typing_listener = TypingListener(
            on_key_press=self._typing_bridge.pulse.emit,
            on_hotkey_typing=self._typing_bridge.hotkey_typing.emit,
            on_hotkey_mic=self._typing_bridge.hotkey_mic.emit,
            on_hotkey_edit=self._typing_bridge.hotkey_edit.emit,
        )
        self.typing_listener.start()

        # In-window overlay control buttons for interactive mode
        self.btn_typing = QPushButton("⌨️ تایپ: خاموش", self)
        self.btn_mic = QPushButton("🎤 میکروفن: خاموش", self)
        self.btn_typing.setFocusPolicy(Qt.NoFocus)
        self.btn_mic.setFocusPolicy(Qt.NoFocus)
        self.btn_typing.clicked.connect(self.toggle_typing_reactive)
        self.btn_mic.clicked.connect(self.toggle_mic_mode)
        self._update_overlay_buttons_geometry()
        if self.is_locked:
            self.btn_typing.hide()
            self.btn_mic.hide()

        # Dedicated floating glassmorphism controls overlay (always clickable on desktop)
        self.controls_bar = FerroControlsOverlay(self)
        self._update_overlay_buttons_state()

        # System Tray Icon setup
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self._setup_tray()

    def _update_timer_interval(self) -> None:
        target_fps = self.config.perf.fps_cap
        interval_ms = max(4, int(1000.0 / target_fps))
        self.timer.setInterval(interval_ms)

    def _apply_geometry_from_config(self) -> None:
        screen = QGuiApplication.primaryScreen()
        avail_geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        size = self.config.window.size
        x = self.config.window.x
        y = self.config.window.y

        if x < 0 or y < 0:
            # Automatic anchor placement
            anchor = self.config.window.anchor
            margin = self.config.window.margin

            if anchor == "top-left":
                x = avail_geo.left() + margin
                y = avail_geo.top() + margin
            elif anchor == "top-right":
                x = avail_geo.right() - size - margin
                y = avail_geo.top() + margin
            elif anchor == "bottom-left":
                x = avail_geo.left() + margin
                y = avail_geo.bottom() - size - margin
            elif anchor == "center":
                x = avail_geo.left() + (avail_geo.width() - size) // 2
                y = avail_geo.top() + (avail_geo.height() - size) // 2
            else:  # "bottom-right"
                x = avail_geo.right() - size - margin
                y = avail_geo.bottom() - size - margin

        # Clamp within available screen boundaries
        x = max(avail_geo.left(), min(x, avail_geo.right() - size))
        y = max(avail_geo.top(), min(y, avail_geo.bottom() - size))

        self.setGeometry(x, y, size, size)

    def initializeGL(self) -> None:
        """Initialize ModernGL context and shader program inside Qt's GL context."""
        try:
            self.ctx = moderngl.create_context()
            self.renderer = FerroRenderer(self.ctx)
            logger.info("FerroWindow initialized OpenGL 3.3 / ModernGL successfully.")
        except Exception as e:
            logger.error("Failed to initialize OpenGL in FerroWindow: %s", e)

    def resizeGL(self, w: int, h: int) -> None:
        self._cached_qt_fbo = None
        self._cached_fbo_id = -1
        if self.ctx:
            dpr = self.devicePixelRatio()
            self.ctx.viewport = (0, 0, int(w * dpr), int(h * dpr))

    def paintGL(self) -> None:
        """Frame render loop: query features, step physics, bind Qt FBO, render quad."""
        now = time.perf_counter()
        dt = now - self.last_frame_time
        self.last_frame_time = now
        elapsed_time = now - self.start_time

        # FPS metrics calculation
        self.frame_count += 1
        if now - self._fps_timer >= 1.0:
            self.fps_metric = self.frame_count / (now - self._fps_timer)
            self.frame_count = 0
            self._fps_timer = now

        # Get latest audio features
        feat = self.features_provider() if callable(self.features_provider) else Features(
            bands=tuple([0.0]*32), sub=0, bass=0, lowmid=0, mid=0, highmid=0, air=0,
            loudness=0, centroid=0, balance=0, excitement=0, kick=0, snare=0, hat=0,
            beat_phase=0, is_silent=True
        )

        # Maintain silky smooth frame rate (60 FPS in both active and idle, or when typing)
        now_ts = time.perf_counter()
        is_typing_active = self.is_typing_reactive and ((now_ts - self.last_typing_time) < 0.6)
        effective_silent = feat.is_silent and not is_typing_active
        target_fps = (
            self.config.perf.idle_fps
            if (effective_silent and self.config.perf.idle_fps < self.config.perf.fps_cap)
            else self.config.perf.fps_cap
        )
        target_interval = max(4, int(1000.0 / target_fps))
        if self.timer.interval() != target_interval:
            self.timer.setInterval(target_interval)

        # Step physics on GUI thread
        self.sim.update_choreography(feat, dt)

        # Detect and bind Qt's internal FBO (cached to avoid per-frame GL queries)
        if self.ctx and self.renderer:
            fbo_id = self.defaultFramebufferObject()
            if self._cached_qt_fbo is None or self._cached_fbo_id != fbo_id:
                try:
                    self._cached_qt_fbo = self.ctx.detect_framebuffer(fbo_id)
                    self._cached_fbo_id = fbo_id
                except Exception:
                    try:
                        self._cached_qt_fbo = self.ctx.detect_framebuffer()
                        self._cached_fbo_id = fbo_id
                    except Exception:
                        self._cached_qt_fbo = None

            dpr = self.devicePixelRatio()
            render_scale = self.config.perf.render_scale
            fb_w = int(self.width() * dpr * render_scale)
            fb_h = int(self.height() * dpr * render_scale)

            blobs = self.sim.get_blobs_uniform_data()
            magnets = self.sim.get_magnets_uniform_data()

            self.renderer.render_frame(
                width=fb_w,
                height=fb_h,
                time_sec=elapsed_time,
                blobs_data=blobs,
                magnets_data=magnets,
                spike_amount=self.sim.spike,
                edit_mode=(not self.is_locked),
                debug_bg=self.debug_bg,
                look_cfg=self.config.look,
                perf_cfg=self.config.perf,
                target_fbo=self._cached_qt_fbo,
            )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.timer.start()
        self._apply_native_x11_states()
        if hasattr(self, "controls_bar") and self.controls_bar:
            self.controls_bar.update_position()
            if hasattr(self, "act_controls") and self.act_controls:
                if self.act_controls.isChecked():
                    self.controls_bar.show()
            else:
                self.controls_bar.show()

    def hideEvent(self, event) -> None:
        if hasattr(self, "controls_bar") and self.controls_bar:
            self.controls_bar.hide()
        super().hideEvent(event)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if hasattr(self, "controls_bar") and self.controls_bar:
            self.controls_bar.update_position()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.WinIdChange:
            self._apply_native_x11_states()

    def _apply_native_window_states(self) -> None:
        """Apply EWMH sticky/layer hints and click-through on Linux & Windows."""
        win_id = int(self.winId())
        if win_id <= 0:
            return
        if sys.platform.startswith("linux"):
            apply_ewmh_hints(win_id, layer=self.config.window.layer)
            set_click_through(win_id, click_through=self.is_locked, width=self.width(), height=self.height())
        elif sys.platform == "win32":
            set_windows_click_through(win_id, click_through=self.is_locked)

    def _apply_native_x11_states(self) -> None:
        self._apply_native_window_states()

    def set_locked(self, locked: bool) -> None:
        """Toggle between LOCKED (click-through overlay) and EDIT (movable, resizable)."""
        self.is_locked = locked
        self.config.window.locked = locked
        self._apply_native_window_states()
        if hasattr(self, "btn_typing") and hasattr(self, "btn_mic"):
            if locked:
                self.btn_typing.hide()
                self.btn_mic.hide()
            else:
                self._update_overlay_buttons_geometry()
                self.btn_typing.show()
                self.btn_mic.show()
        if hasattr(self, "act_edit") and self.act_edit:
            self.act_edit.setChecked(not locked)
        if locked:
            # Save geometry to config when exiting edit mode
            geo = self.geometry()
            self.config.window.x = geo.x()
            self.config.window.y = geo.y()
            self.config.window.size = geo.width()
            self.config.save()
            logger.info("Locked FerroWidget at (%d, %d), size %d", geo.x(), geo.y(), geo.width())
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.is_locked:
            return
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_start_pos = event.globalPosition().toPoint()
            self._drag_window_pos = self.pos()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.is_locked or not self._dragging:
            return
        delta = event.globalPosition().toPoint() - self._drag_start_pos
        new_pos = self._drag_window_pos + delta
        self.move(new_pos)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self.is_locked and event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if not self.is_locked:
            self.set_locked(True)
            event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.is_locked:
            return
        # Resize square geometry with wheel
        delta = event.angleDelta().y()
        step = 20 if delta > 0 else -20
        new_size = max(128, min(1200, self.width() + step))
        # Keep center pinned
        center = self.geometry().center()
        new_x = center.x() - new_size // 2
        new_y = center.y() - new_size // 2
        self.setGeometry(new_x, new_y, new_size, new_size)
        self.config.window.size = new_size
        event.accept()

    def keyPressEvent(self, event) -> None:
        if not self.is_locked and event.key() == Qt.Key_Escape:
            self.set_locked(True)
            event.accept()
            return

        # Global hotkeys: Ctrl+Shift+T for typing reactive, Ctrl+Shift+M for mic mode, Ctrl+Shift+E for edit mode
        if (event.modifiers() & Qt.ControlModifier) and (event.modifiers() & Qt.ShiftModifier):
            if event.key() == Qt.Key_T:
                self.toggle_typing_reactive()
                event.accept()
                return
            elif event.key() == Qt.Key_M:
                self.toggle_mic_mode()
                event.accept()
                return
            elif event.key() == Qt.Key_E:
                self.set_locked(not self.is_locked)
                event.accept()
                return

        # In-app key press reactivity
        if self.is_typing_reactive:
            self._on_typing_pulse_gui()

        super().keyPressEvent(event)

    def _setup_tray(self) -> None:
        """Create procedural tray icon and context menu."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.info("System tray is not available on this desktop session.")
            return

        # Generate a procedural glossy droplet icon (32x32)
        icon_pixmap = QPixmap(32, 32)
        icon_pixmap.fill(Qt.transparent)
        painter = QPainter(icon_pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # Deep obsidian black droplet
        painter.setBrush(QColor(15, 17, 20))
        painter.setPen(QColor(180, 190, 205, 180))
        painter.drawEllipse(4, 4, 24, 24)
        # Specular glint
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(10, 8, 5, 5)
        painter.end()

        self.tray_icon = QSystemTrayIcon(QIcon(icon_pixmap), self)
        menu = QMenu()

        # 1. Edit mode toggle
        self.act_edit = QAction("Edit Position & Size", menu)
        self.act_edit.setCheckable(True)
        self.act_edit.setChecked(not self.is_locked)
        self.act_edit.triggered.connect(lambda chk: self.set_locked(not chk))
        menu.addAction(self.act_edit)

        # 2. Controls overlay toggle
        self.act_controls = QAction("🎛️ نمایش دکمه‌های کنترل (Show Controls)", menu)
        self.act_controls.setCheckable(True)
        self.act_controls.setChecked(True)
        self.act_controls.triggered.connect(lambda chk: self.controls_bar.setVisible(chk))
        menu.addAction(self.act_controls)

        menu.addSeparator()

        # 2. Typing reactive mode toggle
        self.act_typing = QAction("⌨️ حساس به تایپ (Typing Reactive)", menu)
        self.act_typing.setCheckable(True)
        self.act_typing.setChecked(self.is_typing_reactive)
        self.act_typing.triggered.connect(lambda chk: self.set_typing_reactive(chk))
        menu.addAction(self.act_typing)

        # 3. Microphone input mode toggle
        self.act_mic = QAction("🎤 روشن کردن میکروفن (Microphone Input)", menu)
        self.act_mic.setCheckable(True)
        self.act_mic.setChecked(self.is_mic_mode)
        self.act_mic.triggered.connect(lambda chk: self.set_mic_mode(chk))
        menu.addAction(self.act_mic)

        menu.addSeparator()

        # 4. Themes submenu
        theme_menu = menu.addMenu("Theme")
        for t_name in THEMES.keys():
            act = QAction(t_name.capitalize(), theme_menu)
            act.triggered.connect(lambda _, name=t_name: self.set_theme(name))
            theme_menu.addAction(act)

        # 5. Presets submenu
        preset_menu = menu.addMenu("Physics Preset")
        for p_name in ("calm", "club", "cinematic"):
            act = QAction(p_name.capitalize(), preset_menu)
            act.triggered.connect(lambda _, name=p_name: self.set_preset(name))
            preset_menu.addAction(act)

        # 6. Sizes submenu
        size_menu = menu.addMenu("Size")
        for s_val in (256, 360, 420, 600, 800):
            act = QAction(f"{s_val} px", size_menu)
            act.triggered.connect(lambda _, s=s_val: self.set_size(s))
            size_menu.addAction(act)

        menu.addSeparator()

        # 7. Reload Config
        act_reload = QAction("Reload Config", menu)
        act_reload.triggered.connect(self.reload_config)
        menu.addAction(act_reload)

        # 8. Quit
        act_quit = QAction("Quit FerroWidget", menu)
        act_quit.triggered.connect(QGuiApplication.instance().quit)
        menu.addAction(act_quit)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

    def _on_typing_pulse_gui(self) -> None:
        """Invoked on Qt main GUI thread upon keyboard event."""
        if not self.is_typing_reactive:
            return
        self.sim.inject_typing_impulse(strength=1.0)
        self.last_typing_time = time.perf_counter()
        self.update()

    def set_typing_reactive(self, enabled: bool) -> None:
        """Enable or disable fluid reactivity to keyboard typing."""
        self.is_typing_reactive = bool(enabled)
        self.config.audio.typing_reactive = self.is_typing_reactive
        if self.is_typing_reactive:
            self.typing_listener.start()
        else:
            self.typing_listener.stop()
        if hasattr(self, "act_typing") and self.act_typing:
            self.act_typing.setChecked(self.is_typing_reactive)
        self._update_overlay_buttons_state()
        self.config.save()
        logger.info("Typing reactive mode: %s", self.is_typing_reactive)
        self.update()

    def toggle_typing_reactive(self) -> bool:
        self.set_typing_reactive(not self.is_typing_reactive)
        return self.is_typing_reactive

    def set_mic_mode(self, enabled: bool) -> None:
        """Switch audio input between microphone and system playback monitor."""
        self.is_mic_mode = bool(enabled)
        self.config.audio.mic_mode = self.is_mic_mode
        if self.audio_capture and hasattr(self.audio_capture, "set_mic_mode"):
            self.audio_capture.set_mic_mode(self.is_mic_mode)
        if hasattr(self, "act_mic") and self.act_mic:
            self.act_mic.setChecked(self.is_mic_mode)
        self._update_overlay_buttons_state()
        self.config.save()
        logger.info("Microphone mode: %s", self.is_mic_mode)
        self.update()

    def toggle_mic_mode(self) -> bool:
        self.set_mic_mode(not self.is_mic_mode)
        return self.is_mic_mode

    def _update_overlay_buttons_state(self) -> None:
        if hasattr(self, "controls_bar") and self.controls_bar:
            self.controls_bar.update_states()
        if not hasattr(self, "btn_typing") or not hasattr(self, "btn_mic"):
            return
        style_off = (
            "QPushButton { background: rgba(18, 22, 28, 0.85); color: #c4d0dc; "
            "border: 1px solid rgba(255, 255, 255, 0.16); border-radius: 14px; "
            "font-size: 11px; font-weight: 500; padding: 2px 8px; }"
            "QPushButton:hover { background: rgba(32, 38, 48, 0.95); color: #fff; border-color: rgba(0, 229, 255, 0.5); }"
        )
        style_on = (
            "QPushButton { background: #00e5ff; color: #05070a; "
            "border: 1px solid #00e5ff; border-radius: 14px; "
            "font-size: 11px; font-weight: 700; padding: 2px 8px; }"
            "QPushButton:hover { background: #33ebff; border-color: #33ebff; }"
        )
        if self.is_typing_reactive:
            self.btn_typing.setStyleSheet(style_on)
            self.btn_typing.setText("⌨️ تایپ: فعال")
            self.btn_typing.setToolTip("حالت حساس به تایپ فعال است (کلیک برای خاموش کردن)")
        else:
            self.btn_typing.setStyleSheet(style_off)
            self.btn_typing.setText("⌨️ تایپ: خاموش")
            self.btn_typing.setToolTip("کلیک برای فعال کردن واکنش فروسیال به تایپ کیبورد")

        if self.is_mic_mode:
            self.btn_mic.setStyleSheet(style_on)
            self.btn_mic.setText("🎤 میکروفن: فعال")
            self.btn_mic.setToolTip("ورودی میکروفن فعال است (کلیک برای بازگشت به صدای سیستم)")
        else:
            self.btn_mic.setStyleSheet(style_off)
            self.btn_mic.setText("🎤 میکروفن: خاموش")
            self.btn_mic.setToolTip("کلیک برای روشن کردن میکروفن و واکنش به صدای محیط")

    def _update_overlay_buttons_geometry(self) -> None:
        if not hasattr(self, "btn_typing") or not hasattr(self, "btn_mic"):
            return
        btn_w = 115
        btn_h = 28
        gap = 8
        total_w = btn_w * 2 + gap
        start_x = (self.width() - total_w) // 2
        y = self.height() - btn_h - 16
        self.btn_typing.setGeometry(start_x, y, btn_w, btn_h)
        self.btn_mic.setGeometry(start_x + btn_w + gap, y, btn_w, btn_h)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_overlay_buttons_geometry()
        if hasattr(self, "controls_bar") and self.controls_bar:
            self.controls_bar.update_position()

    def closeEvent(self, event) -> None:
        self.cleanup()
        super().closeEvent(event)

    def cleanup(self) -> None:
        """Tear down background typing listener and controls overlay."""
        if hasattr(self, "typing_listener") and self.typing_listener:
            self.typing_listener.stop()
        if hasattr(self, "controls_bar") and self.controls_bar:
            self.controls_bar.close()

    def set_theme(self, theme_name: str) -> None:
        if theme_name in THEMES:
            self.config.look.theme = theme_name
            self.config.save()
            self.update()

    def set_preset(self, preset_name: str) -> None:
        self.sim._apply_preset_params(preset_name)
        self.config.fluid.preset = preset_name
        self.config.save()
        self.update()

    def set_size(self, size_px: int) -> None:
        size = max(128, min(1200, size_px))
        self.resize(size, size)
        self.config.window.size = size
        self.config.save()
        self._apply_native_x11_states()
        self.update()

    def reload_config(self, config: Optional[AppConfig] = None) -> None:
        self.config = config or AppConfig.load()
        self.sim._apply_preset_params(self.config.fluid.preset)
        self.set_typing_reactive(self.config.audio.typing_reactive)
        self.set_mic_mode(self.config.audio.mic_mode)
        self._apply_geometry_from_config()
        self._apply_native_window_states()
        self.update()
