"""IPC Server and Client using Unix Domain Sockets for ferrowidget ctl."""

from __future__ import annotations

import json
import logging
import os
import socket
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer

logger = logging.getLogger(__name__)


def get_socket_path() -> str:
    """Return runtime socket path in XDG_RUNTIME_DIR or /tmp."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        return os.path.join(runtime_dir, "ferrowidget.sock")
    uid = os.getuid() if hasattr(os, "getuid") else 1000
    return f"/tmp/ferrowidget-{uid}.sock"


class IPCServer(QObject):
    """QLocalServer handling JSON-line control commands from CLI."""

    command_received = Signal(str, dict)  # command_name, payload

    def __init__(self, handler: Optional[Callable[[str, dict], dict]] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.handler = handler
        self.server = QLocalServer(self)
        self.socket_path = get_socket_path()

    def start(self) -> bool:
        """Start listening on unix socket, removing any stale socket file."""
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError as e:
                logger.warning("Could not remove stale socket %s: %s", self.socket_path, e)

        self.server.newConnection.connect(self._on_new_connection)
        ok = self.server.listen(self.socket_path)
        if ok:
            logger.info("IPC server listening on %s", self.socket_path)
        else:
            logger.error("Failed to start IPC server on %s: %s", self.socket_path, self.server.errorString())
        return ok

    def stop(self) -> None:
        """Close server and remove socket file."""
        if self.server.isListening():
            self.server.close()
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass

    def _on_new_connection(self) -> None:
        client_socket = self.server.nextPendingConnection()
        if not client_socket:
            return

        def read_data():
            while client_socket.canReadLine():
                line = bytes(client_socket.readLine()).decode("utf-8").strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    cmd = payload.get("cmd", "")
                    response = {"status": "error", "message": f"Unknown command: {cmd}"}
                    if self.handler:
                        response = self.handler(cmd, payload)
                    client_socket.write((json.dumps(response) + "\n").encode("utf-8"))
                    client_socket.flush()
                except Exception as ex:
                    err_resp = {"status": "error", "message": str(ex)}
                    client_socket.write((json.dumps(err_resp) + "\n").encode("utf-8"))
                    client_socket.flush()
            client_socket.disconnectFromServer()

        client_socket.readyRead.connect(read_data)


def send_ctl_command(cmd: str, args: Optional[Dict[str, Any]] = None, timeout: float = 2.0) -> Dict[str, Any]:
    """Client function: connect to server unix socket, send command, and return response dict."""
    sock_path = get_socket_path()
    if not os.path.exists(sock_path):
        return {"status": "error", "message": f"FerroWidget is not running (socket {sock_path} not found)."}

    payload = {"cmd": cmd}
    if args:
        payload.update(args)

    data = (json.dumps(payload) + "\n").encode("utf-8")

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(sock_path)
        client.sendall(data)
        response_bytes = b""
        while b"\n" not in response_bytes:
            chunk = client.recv(4096)
            if not chunk:
                break
            response_bytes += chunk
        line = response_bytes.decode("utf-8").strip()
        if not line:
            return {"status": "error", "message": "Empty response from server."}
        return json.loads(line)
    except Exception as e:
        return {"status": "error", "message": f"IPC error: {e}"}
    finally:
        client.close()
