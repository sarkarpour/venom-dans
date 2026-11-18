"""Integration tests for CLI entry points, Unix domain socket IPC, and audio lifecycle."""

import argparse
import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from ferrowidget.audio.capture import AudioCaptureThread, get_default_monitor_source
from ferrowidget.cli import cmd_ctl, cmd_doctor, cmd_dump_frame
from ferrowidget.ipc import IPCServer, send_ctl_command


def test_cli_doctor():
    """Verify ferrowidget doctor executes cleanly and returns exit code 0."""
    args = argparse.Namespace()
    ret = cmd_doctor(args)
    assert ret == 0


def test_monitor_source_resolution():
    """Verify default monitor source can be resolved."""
    src = get_default_monitor_source()
    assert src is not None
    assert isinstance(src, str)
    assert len(src) > 0


def test_cli_ctl_input_validation():
    """Verify cmd_ctl cleanly handles invalid arguments without uncaught exceptions."""
    # Size with non-integer string
    args_bad_size = argparse.Namespace(command="size", args=["notanumber"])
    assert cmd_ctl(args_bad_size) == 1

    # Move with missing y
    args_bad_move1 = argparse.Namespace(command="move", args=["100"])
    assert cmd_ctl(args_bad_move1) == 1

    # Move with non-integer y
    args_bad_move2 = argparse.Namespace(command="move", args=["100", "invalid"])
    assert cmd_ctl(args_bad_move2) == 1

    # Theme with no theme name
    args_bad_theme = argparse.Namespace(command="theme", args=[])
    assert cmd_ctl(args_bad_theme) == 1

    # Typing with invalid mode
    args_bad_typing = argparse.Namespace(command="typing", args=["badmode"])
    assert cmd_ctl(args_bad_typing) == 1

    # Mic with invalid mode
    args_bad_mic = argparse.Namespace(command="mic", args=["badmode"])
    assert cmd_ctl(args_bad_mic) == 1


def test_audio_capture_lifecycle_and_features():
    """Verify AudioCaptureThread synthetic mode produces valid features and terminates cleanly."""
    thread = AudioCaptureThread(synthetic_source="kick120")
    thread.start()

    time.sleep(0.3)
    feat = thread.latest_features
    assert feat is not None
    assert len(feat.bands) == 32
    assert not feat.is_silent

    # Toggle mic mode
    thread.set_mic_mode(True)
    assert thread.mic_mode is True
    thread.set_mic_mode(False)
    assert thread.mic_mode is False

    thread.stop()
    thread.join(timeout=2.0)
    assert not thread.is_alive()


def test_dump_frame_all_eight_moments():
    """Verify dump-frame creates all 8 key moments and contact sheet."""
    with tempfile.TemporaryDirectory() as tmpdir:
        args = argparse.Namespace(
            synthetic="kick120",
            frames=1,
            seed=42,
            out=tmpdir,
            theme="ink",
            contact_sheet=True,
        )
        ret = cmd_dump_frame(args)
        assert ret == 0

        out_path = Path(tmpdir)
        expected_moments = [
            "frame_idle.png",
            "frame_steady_bass.png",
            "frame_kick_0ms.png",
            "frame_kick_50ms.png",
            "frame_kick_120ms.png",
            "frame_kick_250ms.png",
            "frame_full_mix.png",
            "frame_max_spikes.png",
            "contact_sheet.png",
        ]
        for name in expected_moments:
            f = out_path / name
            assert f.exists(), f"Expected output {name} missing from dump-frame"
            assert f.stat().st_size > 0, f"Output {name} is empty"


def test_ipc_roundtrip():
    """Verify JSON-line protocol over Unix socket between client and server."""
    import threading

    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    received_cmds = []

    def mock_handler(cmd: str, payload: dict) -> dict:
        received_cmds.append((cmd, payload))
        if cmd == "edit":
            return {"status": "ok", "locked": False}
        elif cmd == "theme":
            return {"status": "ok", "theme": payload.get("name")}
        elif cmd == "typing":
            return {"status": "ok", "typing_reactive": payload.get("mode") == "on"}
        elif cmd == "mic":
            return {"status": "ok", "mic_mode": payload.get("mode") == "on"}
        elif cmd == "status":
            return {"status": "ok", "fps": 60.0, "typing_reactive": True, "mic_mode": False}
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

        # Send 'typing' command
        resp_typing = call_cmd("typing", {"mode": "on"})
        assert resp_typing.get("status") == "ok"
        assert resp_typing.get("typing_reactive") is True

        # Send 'mic' command
        resp_mic = call_cmd("mic", {"mode": "off"})
        assert resp_mic.get("status") == "ok"
        assert resp_mic.get("mic_mode") is False

        # Send 'status' command
        resp_status = call_cmd("status")
        assert resp_status.get("status") == "ok"
        assert resp_status.get("fps") == 60.0
        assert resp_status.get("typing_reactive") is True
        assert resp_status.get("mic_mode") is False

        assert len(received_cmds) == 5
    finally:
        server.stop()
