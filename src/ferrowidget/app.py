"""QApplication lifecycle, IPC handler, signal handling, and exit timer."""

from __future__ import annotations

import logging
import os
import signal
import sys
from typing import Any, Dict, Optional

from PySide6.QtCore import QFileSystemWatcher, QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from ferrowidget.audio.capture import AudioCaptureThread
from ferrowidget.config import DEFAULT_CONFIG_PATH, AppConfig
from ferrowidget.ipc import IPCServer
from ferrowidget.physics.fluid import FluidSimulation
from ferrowidget.window import FerroWindow

logger = logging.getLogger(__name__)


def setup_surface_format() -> None:
    """Configure default OpenGL surface format for per-pixel alpha transparency."""
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.OpenGL)
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setAlphaBufferSize(8)
    fmt.setRedBufferSize(8)
    fmt.setGreenBufferSize(8)
    fmt.setBlueBufferSize(8)
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(0)
    fmt.setSamples(0)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)


class FerroApp:
    """Coordinates QApplication, audio thread, physics, window, IPC server, and signals."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        synthetic_source: Optional[str] = None,
        debug_bg: str = "none",
        wayland_native: bool = False,
        exit_after: Optional[float] = None,
        override_x: Optional[int] = None,
        override_y: Optional[int] = None,
        override_size: Optional[int] = None,
        override_anchor: Optional[str] = None,
    ):
        # Platform selection: enforce X11/xcb on Linux by default
        if sys.platform.startswith("linux"):
            if not wayland_native and "QT_QPA_PLATFORM" not in os.environ:
                os.environ["QT_QPA_PLATFORM"] = "xcb"
            if "QT_XCB_GL_INTEGRATION" not in os.environ:
                os.environ["QT_XCB_GL_INTEGRATION"] = "xcb_egl"

        setup_surface_format()

        # Initialize QApplication
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)
        self.app.setApplicationName("FerroWidget")
        self.app.setQuitOnLastWindowClosed(False)

        # Config setup
        self.config = config or AppConfig.load()
        if override_x is not None:
            self.config.window.x = override_x
        if override_y is not None:
            self.config.window.y = override_y
        if override_size is not None:
            self.config.window.size = override_size
        if override_anchor is not None:
            self.config.window.anchor = override_anchor

        # Debug background
        bg_map = {"none": 0, "dark": 1, "light": 2, "checker": 3}
        self.debug_bg_idx = bg_map.get(debug_bg.lower(), 0)

        # Audio capture thread
        self.audio_thread = AudioCaptureThread(
            source=self.config.audio.source,
            sensitivity=self.config.audio.sensitivity,
            visual_delay_ms=self.config.audio.visual_delay_ms,
            synthetic_source=synthetic_source,
            mic_mode=self.config.audio.mic_mode,
        )

        # Physics simulation
        self.sim = FluidSimulation(preset=self.config.fluid.preset)

        # Window
        self.window = FerroWindow(
            config=self.config,
            simulation=self.sim,
            features_provider=lambda: self.audio_thread.latest_features,
            debug_bg=self.debug_bg_idx,
            audio_capture=self.audio_thread,
        )

        # IPC Server
        self.ipc = IPCServer(handler=self._handle_ipc_command)

        # Config file watcher for live hot-reload
        self.watcher = QFileSystemWatcher()
        if DEFAULT_CONFIG_PATH.exists():
            self.watcher.addPath(str(DEFAULT_CONFIG_PATH))
            self.watcher.fileChanged.connect(self._on_config_file_changed)

        # Exit-after timer
        if exit_after and exit_after > 0:
            logger.info("Setting exit timer for %.2f seconds", exit_after)
            QTimer.singleShot(int(exit_after * 1000), self.shutdown)

        # Signal handlers for graceful SIGINT and SIGTERM
        self._setup_signals()

    def _setup_signals(self) -> None:
        def handle_signal(sig, frame):
            logger.info("Received signal %d, shutting down...", sig)
            self.shutdown()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        # Keep Python signal processing alive via small periodic QTimer
        self.sig_timer = QTimer()
        self.sig_timer.timeout.connect(lambda: None)
        self.sig_timer.start(250)

    def _on_config_file_changed(self, path: str) -> None:
        logger.info("Config file changed on disk, reloading...")
        self.config = AppConfig.load()
        self.window.reload_config(self.config)
        # Re-add path in case file replacement broke the watch
        if os.path.exists(path):
            self.watcher.addPath(path)

    def _handle_ipc_command(self, cmd: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle control commands sent via `ferrowidget ctl`."""
        try:
            if cmd == "edit":
                mode = payload.get("mode", "toggle")
                if mode == "on":
                    self.window.set_locked(False)
                elif mode == "off":
                    self.window.set_locked(True)
                else:  # toggle
                    self.window.set_locked(not self.window.is_locked)
                self.config = self.window.config
                return {"status": "ok", "locked": self.window.is_locked}

            elif cmd == "pause":
                self.audio_thread.pause()
                return {"status": "ok", "message": "Audio capture paused."}

            elif cmd == "resume":
                self.audio_thread.resume()
                return {"status": "ok", "message": "Audio capture resumed."}

            elif cmd == "theme":
                name = payload.get("name", "ink")
                self.window.set_theme(name)
                self.config = self.window.config
                return {"status": "ok", "theme": self.window.config.look.theme}

            elif cmd == "preset":
                name = payload.get("name", "club")
                self.window.set_preset(name)
                self.config = self.window.config
                return {"status": "ok", "preset": self.window.config.fluid.preset}

            elif cmd == "size":
                size = int(payload.get("size", 420))
                self.window.set_size(size)
                self.config = self.window.config
                return {"status": "ok", "size": self.window.config.window.size}

            elif cmd == "move":
                x = int(payload.get("x", 0))
                y = int(payload.get("y", 0))
                self.window.move(x, y)
                self.window.config.window.x = x
                self.window.config.window.y = y
                self.window.config.save()
                self.config = self.window.config
                return {"status": "ok", "x": x, "y": y}

            elif cmd == "reload":
                self.config = AppConfig.load()
                self.window.reload_config(self.config)
                return {"status": "ok", "message": "Config reloaded."}

            elif cmd == "typing":
                mode = payload.get("mode", "toggle")
                if mode == "on":
                    self.window.set_typing_reactive(True)
                elif mode == "off":
                    self.window.set_typing_reactive(False)
                else:
                    self.window.toggle_typing_reactive()
                self.config = self.window.config
                return {"status": "ok", "typing_reactive": self.window.is_typing_reactive}

            elif cmd == "mic":
                mode = payload.get("mode", "toggle")
                if mode == "on":
                    self.window.set_mic_mode(True)
                elif mode == "off":
                    self.window.set_mic_mode(False)
                else:
                    self.window.toggle_mic_mode()
                self.config = self.window.config
                return {"status": "ok", "mic_mode": self.window.is_mic_mode}

            elif cmd == "status":
                geo = self.window.geometry()
                feat = self.audio_thread.latest_features
                return {
                    "status": "ok",
                    "locked": self.window.is_locked,
                    "geometry": {"x": geo.x(), "y": geo.y(), "w": geo.width(), "h": geo.height()},
                    "fps": round(self.window.fps_metric, 1),
                    "theme": self.window.config.look.theme,
                    "preset": self.window.config.fluid.preset,
                    "typing_reactive": self.window.is_typing_reactive,
                    "mic_mode": self.window.is_mic_mode,
                    "audio_silent": feat.is_silent,
                    "loudness": round(feat.loudness, 2),
                    "kick": round(feat.kick, 2),
                }

            elif cmd == "quit":
                QTimer.singleShot(50, self.shutdown)
                return {"status": "ok", "message": "Shutting down FerroWidget."}

            else:
                return {"status": "error", "message": f"Unknown command '{cmd}'"}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def run(self) -> int:
        """Start threads, show window, listen on IPC socket, and start Qt event loop."""
        self.audio_thread.start()
        self.ipc.start()
        self.window.show()
        return self.app.exec()

    def shutdown(self) -> None:
        """Cleanly tear down audio thread, IPC socket, and exit application."""
        logger.info("FerroApp shutting down...")
        self.audio_thread.stop()
        self.ipc.stop()
        self.window.cleanup()
        self.window.close()
        self.app.quit()
