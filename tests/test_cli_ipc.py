"""Integration tests for CLI entry points and Unix domain socket IPC."""

import argparse
import time

from PySide6.QtCore import QCoreApplication

from ferrowidget.cli import cmd_doctor
from ferrowidget.ipc import IPCServer, send_ctl_command


def test_cli_doctor():
    """Verify ferrowidget doctor executes cleanly and returns exit code 0."""
    args = argparse.Namespace()
    ret = cmd_doctor(args)
    assert ret == 0


def test_ipc_roundtrip():
    """Verify JSON-line protocol over Unix socket between client and server."""
    import threading

    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])

    received_cmds = []

    def mock_handler(cmd: str, payload: dict) -> dict:
        received_cmds.append((cmd, payload))
        if cmd == "edit":
            return {"status": "ok", "locked": False}
        elif cmd == "theme":
            return {"status": "ok", "theme": payload.get("name")}
        elif cmd == "status":
            return {"status": "ok", "fps": 60.0}
        return {"status": "ok"}

    server = IPCServer(handler=mock_handler)
    assert server.start() is True

    def call_cmd(cmd: str, args=None):
        out = {}
        def worker():
            out.update(send_ctl_command(cmd, args))
        t = threading.Thread(target=worker)
        t.start()
        t0 = time.time()
        while t.is_alive() and time.time() - t0 < 2.0:
            app.processEvents()
            time.sleep(0.005)
        t.join()
        return out

    try:
        # Send 'edit' command
        resp_edit = call_cmd("edit", {"mode": "off"})
        assert resp_edit.get("status") == "ok"
        assert resp_edit.get("locked") is False

        # Send 'theme' command
        resp_theme = call_cmd("theme", {"name": "neon"})
        assert resp_theme.get("status") == "ok"
        assert resp_theme.get("theme") == "neon"

        # Send 'status' command
        resp_status = call_cmd("status")
        assert resp_status.get("status") == "ok"
        assert resp_status.get("fps") == 60.0

        assert len(received_cmds) == 3
    finally:
        server.stop()
