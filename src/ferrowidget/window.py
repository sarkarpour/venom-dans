"""Frameless, transparent OpenGL desktop window with locked/edit modes and system tray."""

from __future__ import annotations

import logging
import time
from typing import Optional

import moderngl
from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
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
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ferrowidget.audio.analysis import Features
from ferrowidget.config import AppConfig
from ferrowidget.physics.fluid import FluidSimulation
from ferrowidget.render.renderer import THEMES, FerroRenderer
from ferrowidget.x11 import apply_ewmh_hints, set_click_through

logger = logging.getLogger(__name__)


class FerroWindow(QOpenGLWidget):
    """Transparent, frameless, click-through desktop overlay rendering photorealistic ferrofluid."""

    def __init__(
        self,
        config: AppConfig,
        simulation: FluidSimulation,
        features_provider,
        debug_bg: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.config = config
        self.sim = simulation
        self.features_provider = features_provider
        self.debug_bg = debug_bg

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

        # Maintain silky smooth frame rate (60 FPS in both active and idle)
        target_fps = self.config.perf.idle_fps if (feat.is_silent and self.config.perf.idle_fps < self.config.perf.fps_cap) else self.config.perf.fps_cap
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

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.WinIdChange:
            self._apply_native_x11_states()

    def _apply_native_x11_states(self) -> None:
        """Apply EWMH sticky/layer hints and XShape click-through mask."""
        win_id = int(self.winId())
        if win_id <= 0:
            return

        apply_ewmh_hints(win_id, layer=self.config.window.layer)
        set_click_through(win_id, click_through=self.is_locked, width=self.width(), height=self.height())

    def set_locked(self, locked: bool) -> None:
        """Toggle between LOCKED (click-through overlay) and EDIT (movable, resizable)."""
        self.is_locked = locked
        self.config.window.locked = locked
        win_id = int(self.winId())
        if win_id > 0:
            set_click_through(win_id, click_through=locked, width=self.width(), height=self.height())
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
        else:
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

        menu.addSeparator()

        # 2. Themes submenu
        theme_menu = menu.addMenu("Theme")
        for t_name in THEMES.keys():
            act = QAction(t_name.capitalize(), theme_menu)
            act.triggered.connect(lambda _, name=t_name: self.set_theme(name))
            theme_menu.addAction(act)

        # 3. Presets submenu
        preset_menu = menu.addMenu("Physics Preset")
        for p_name in ("calm", "club", "cinematic"):
            act = QAction(p_name.capitalize(), preset_menu)
            act.triggered.connect(lambda _, name=p_name: self.set_preset(name))
            preset_menu.addAction(act)

        # 4. Sizes submenu
        size_menu = menu.addMenu("Size")
        for s_val in (256, 360, 420, 600, 800):
            act = QAction(f"{s_val} px", size_menu)
            act.triggered.connect(lambda _, s=s_val: self.set_size(s))
            size_menu.addAction(act)

        menu.addSeparator()

        # 5. Reload Config
        act_reload = QAction("Reload Config", menu)
        act_reload.triggered.connect(self.reload_config)
        menu.addAction(act_reload)

        # 6. Quit
        act_quit = QAction("Quit FerroWidget", menu)
        act_quit.triggered.connect(QGuiApplication.instance().quit)
        menu.addAction(act_quit)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

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
        self._apply_geometry_from_config()
        self._apply_native_x11_states()
        self.update()
