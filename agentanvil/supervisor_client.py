"""
Heartbeat client for agentanvil-supervisor.

If `AGENTANVIL_SUPER_SOCK` is exported by the supervisor, this client opens the
Unix socket and streams one-JSON-per-line heartbeats. If the env var is absent
or the socket cannot be reached, every method becomes a silent no-op — so the
exact same Python script runs correctly whether it was launched standalone or
under supervision.

Design notes:
- No dependency outside the stdlib.
- Errors on the socket path (disconnect, broken pipe) degrade to no-op rather
  than raising — the supervisor is optional infrastructure; the rollout must
  not fail because the sidecar hiccupped.
- The message shape matches the `Heartbeat` enum in supervisor/src/main.rs
  exactly (tag="type", snake_case variants).
"""
from __future__ import annotations

import json
import os
import socket
from typing import Optional


class SupervisorClient:
    def __init__(self, sock_path: Optional[str] = None):
        self.path = sock_path if sock_path is not None else os.environ.get("AGENTANVIL_SUPER_SOCK")
        self.sock: Optional[socket.socket] = None
        if self.path:
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(self.path)
                self.sock = s
            except OSError:
                self.sock = None

    @property
    def active(self) -> bool:
        return self.sock is not None

    def _send(self, msg: dict) -> None:
        if self.sock is None:
            return
        try:
            self.sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        except OSError:
            self.sock = None

    def start(self, trajectory_id: Optional[str] = None, pid: Optional[int] = None) -> None:
        self._send({"type": "start", "trajectory_id": trajectory_id, "pid": pid or os.getpid()})

    def progress(self, step: int, note: Optional[str] = None) -> None:
        self._send({"type": "progress", "step": int(step), "note": note})

    def finish(self, ok: bool, final_answer: Optional[str] = None) -> None:
        self._send({"type": "finish", "ok": bool(ok), "final_answer": final_answer})

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
