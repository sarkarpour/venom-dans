"""Guarded X11 EWMH and XShape click-through helpers."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_display = None
_xlib_available = False

try:
    import Xlib.display
    import Xlib.X
    import Xlib.Xatom
    from Xlib.ext import shape
    _xlib_available = True
except Exception as e:
    logger.debug("Xlib not available: %s", e)


def get_x11_display():
    """Lazily obtain cached X11 display connection."""
    global _display
    if not _xlib_available:
        return None
    if _display is None:
        try:
            _display = Xlib.display.Display()
        except Exception as e:
            logger.warning("Could not connect to X11 display: %s", e)
            return None
    return _display


def apply_ewmh_hints(win_id: int, layer: str = "top") -> bool:
    """Apply sticky, skip taskbar, skip pager, and layer hints to window."""
    d = get_x11_display()
    if d is None or win_id <= 0:
        return False

    try:
        w = d.create_resource_object("window", win_id)

        net_wm_state = d.intern_atom("_NET_WM_STATE")
        state_names = [
            "_NET_WM_STATE_STICKY",
            "_NET_WM_STATE_SKIP_TASKBAR",
            "_NET_WM_STATE_SKIP_PAGER",
        ]
        if layer == "top":
            state_names.append("_NET_WM_STATE_ABOVE")
        elif layer == "bottom":
            state_names.append("_NET_WM_STATE_BELOW")

        state_atoms = [d.intern_atom(name) for name in state_names]
        w.change_property(net_wm_state, Xlib.Xatom.ATOM, 32, state_atoms)

        net_wm_type = d.intern_atom("_NET_WM_WINDOW_TYPE")
        type_atom = [d.intern_atom("_NET_WM_WINDOW_TYPE_UTILITY")]
        w.change_property(net_wm_type, Xlib.Xatom.ATOM, 32, type_atom)

        d.sync()
        return True
    except Exception as e:
        logger.warning("Failed to apply EWMH hints to window %d: %s", win_id, e)
        return False


def set_click_through(win_id: int, click_through: bool, width: int = 1000, height: int = 1000) -> bool:
    """Set XShape input shape: empty for click-through, full rectangle for interactive."""
    d = get_x11_display()
    if d is None or win_id <= 0:
        return False

    try:
        w = d.create_resource_object("window", win_id)
        if click_through:
            # Empty list of rectangles means no input hits this window
            w.shape_rectangles(shape.SO.Set, shape.SK.Input, 0, 0, 0, [])
        else:
            # Restore bounding rectangle
            w.shape_rectangles(
                shape.SO.Set,
                shape.SK.Input,
                0,
                0,
                0,
                [(0, 0, max(1, width), max(1, height))],
            )
        d.sync()
        return True
    except Exception as e:
        logger.warning("Failed to update XShape click-through for window %d: %s", win_id, e)
        return False
