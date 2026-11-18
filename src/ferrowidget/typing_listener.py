"""Global keyboard typing listener for reactive ferrofluid spikes on Windows & Linux."""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class TypingListener:
    """Detects global keyboard typing across desktop applications and triggers reactive pulses."""

    def __init__(self, on_key_press: Optional[Callable[[], None]] = None):
        self.on_key_press = on_key_press
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_trigger_time = 0.0
        self._min_interval = 0.025  # 25 ms debounce (~40 keystrokes/sec max)

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def start(self) -> None:
        """Start background keyboard monitoring thread if not already running."""
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="TypingListenerThread",
            daemon=True,
        )
        self._thread.start()
        logger.info("TypingListener started (platform: %s)", sys.platform)

    def stop(self) -> None:
        """Signal thread to cleanly terminate."""
        if not self._running.is_set():
            return
        self._running.clear()
        if self._thread and self._thread.is_alive():
            # For Windows hook thread, post WM_QUIT message
            if sys.platform == "win32":
                self._unhook_windows()
            self._thread.join(timeout=0.6)
        self._thread = None
        logger.info("TypingListener stopped.")

    def trigger(self, strength: float = 1.0) -> None:
        """Explicitly fire a typing pulse event (used by tests and in-app Qt events)."""
        now = time.perf_counter()
        if now - self._last_trigger_time < self._min_interval:
            return
        self._last_trigger_time = now
        if callable(self.on_key_press):
            try:
                self.on_key_press()
            except Exception as e:
                logger.debug("Error in on_key_press callback: %s", e)

    def _worker_loop(self) -> None:
        """Platform-specific event loop."""
        if sys.platform == "win32":
            self._run_windows_loop()
        elif sys.platform.startswith("linux"):
            self._run_linux_x11_loop()
        else:
            self._run_generic_idle_loop()

    def _run_generic_idle_loop(self) -> None:
        """Fallback for non-supported or headless environments."""
        while self._running.is_set():
            time.sleep(0.1)

    # -------------------------------------------------------------
    # Windows Low-Level Hook & Polling
    # -------------------------------------------------------------
    def _run_windows_loop(self) -> None:
        """Windows keyboard detection via low-level hook or GetAsyncKeyState fallback."""
        try:
            import ctypes
            from ctypes import CFUNCTYPE, c_int, wintypes

            user32 = ctypes.windll.user32  # type: ignore
            kernel32 = ctypes.windll.kernel32  # type: ignore

            WH_KEYBOARD_LL = 13
            WM_KEYDOWN = 0x0100
            WM_SYSKEYDOWN = 0x0104

            HOOKPROC = CFUNCTYPE(c_int, c_int, wintypes.WPARAM, wintypes.LPARAM)

            def hook_proc(nCode, wParam, lParam):
                if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    self.trigger()
                return user32.CallNextHookEx(self._windows_hook, nCode, wParam, lParam)

            self._windows_proc = HOOKPROC(hook_proc)
            self._windows_thread_id = kernel32.GetCurrentThreadId()

            self._windows_hook = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL,
                self._windows_proc,
                kernel32.GetModuleHandleW(None),
                0,
            )

            if not self._windows_hook:
                logger.warning("SetWindowsHookExW failed, falling back to GetAsyncKeyState polling.")
                self._run_windows_async_poll(user32)
                return

            msg = wintypes.MSG()
            while self._running.is_set():
                res = user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1)  # PM_REMOVE = 1
                if res > 0:
                    if msg.message == 0x0012:  # WM_QUIT
                        break
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.01)

            if self._windows_hook:
                user32.UnhookWindowsHookEx(self._windows_hook)
                self._windows_hook = None

        except Exception as e:
            logger.debug("Windows hook exception, falling back to polling: %s", e)
            try:
                import ctypes
                self._run_windows_async_poll(ctypes.windll.user32)  # type: ignore
            except Exception:
                self._run_generic_idle_loop()

    def _unhook_windows(self) -> None:
        try:
            import ctypes
            user32 = ctypes.windll.user32  # type: ignore
            if hasattr(self, "_windows_thread_id") and self._windows_thread_id:
                user32.PostThreadMessageW(self._windows_thread_id, 0x0012, 0, 0)  # WM_QUIT
        except Exception:
            pass

    def _run_windows_async_poll(self, user32) -> None:
        """Poll virtual key states on Windows (0x08 Backspace to 0xDE quote) every 15ms."""
        last_states = bytearray(256)
        while self._running.is_set():
            for vk in range(0x08, 0xE0):
                # High-order bit is set if the key is down
                is_down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                if is_down and not last_states[vk]:
                    self.trigger()
                last_states[vk] = 1 if is_down else 0
            time.sleep(0.015)

    # -------------------------------------------------------------
    # Linux X11 / XWayland Keymap Polling
    # -------------------------------------------------------------
    def _run_linux_x11_loop(self) -> None:
        """Poll X11 keymap using python-xlib for new keydown bit events."""
        disp = None
        try:
            from Xlib import display
            disp = display.Display()
        except Exception as e:
            logger.debug("Xlib Display connection failed (%s), running idle fallback", e)
            self._run_generic_idle_loop()
            return

        last_keymap = bytes(32)
        try:
            while self._running.is_set():
                keymap = disp.query_keymap()
                # Check for any new 0 -> 1 key transitions
                new_press = False
                for i in range(min(len(keymap), len(last_keymap))):
                    if keymap[i] & ~last_keymap[i]:
                        new_press = True
                        break

                if new_press:
                    self.trigger()

                last_keymap = keymap
                time.sleep(0.016)  # ~60 Hz polling rate
        except Exception as e:
            logger.debug("X11 keymap polling error: %s", e)
        finally:
            if disp:
                try:
                    disp.close()
                except Exception:
                    pass
