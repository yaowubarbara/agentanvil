"""
OpenSandbox runtime integration (alibaba/OpenSandbox, 10k⭐ CNCF Landscape).

This is the layer the Rust supervisor deliberately does NOT do — actual
syscall / namespace / cgroup isolation via gVisor, Kata Containers, or
Firecracker microVM. OpenSandbox owns that layer; we route our agents'
tool calls into its execd daemon.

Stack locations:
    AgentAnvil Runner  (orchestration)
      └─ Adapter       (scaffold → unified trajectory)
           └─ ToolCallRouter  ← THIS MODULE
                 └─ OpenSandboxRuntime  (SDK wrapper)
                       └─ opensandbox.OpenSandboxClient  ← PyPI
                             └─ execd daemon (:44772, inside gVisor/Kata pod)

Dep: `pip install opensandbox` (lazy-imported). When absent, pass a stub
client into OpenSandboxRuntime(client=...) for tests.

API contract covered:
    sandbox lifecycle:  create / terminate / renew
    code execution:     stateful Python/JS context (vars persist across
                        calls inside the same context)
    command execution:  subprocess-like shell runs
    file I/O:           read / write inside the sandbox filesystem

This wrapper deliberately does NOT expose every OpenSandbox feature. The
goal is to cover the canonical tool calls (`python.exec`, `shell.run`,
`fs.read`, `fs.write`) that an LLM agent emits. Teams needing niche
features (networking ingress/egress policy, paused-sandbox checkpointing,
GPU workloads) should construct the OpenSandbox client directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class SandboxSpec:
    """Creation parameters for an OpenSandbox sandbox."""

    image: str = "python:3.11-slim"
    timeout_seconds: int = 300
    runtime: str = "gvisor"   # alternatives: "runc" (default), "kata", "firecracker"
    cpu_limit: Optional[float] = None
    memory_mb: Optional[int] = None
    env: dict = None

    def to_create_kwargs(self) -> dict:
        kw = {
            "image": self.image,
            "timeout": self.timeout_seconds,
            "runtime": self.runtime,
        }
        if self.cpu_limit is not None:
            kw["cpu_limit"] = self.cpu_limit
        if self.memory_mb is not None:
            kw["memory_mb"] = self.memory_mb
        if self.env:
            kw["env"] = dict(self.env)
        return kw


@dataclass
class ExecResult:
    """Normalized result of an execd call. Scaffold-agnostic."""

    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    return_value: Any = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and (self.exit_code in (None, 0))

    def to_tool_result_content(self) -> dict:
        """Shape this result into a unified-trajectory tool_result content dict."""
        return {
            "output": self.stdout or (str(self.return_value) if self.return_value is not None else ""),
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class OpenSandboxRuntime:
    """Wrapper around an OpenSandbox client instance.

    Lazy-imports opensandbox on `_build_default_client`. Construct with
    `client=<stub>` to avoid the import (used by tests).
    """

    def __init__(
        self,
        client: Any = None,
        spec: Optional[SandboxSpec] = None,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
    ):
        self.spec = spec or SandboxSpec()
        self._api_key = api_key or os.environ.get("OPEN_SANDBOX_API_KEY")
        self._endpoint = endpoint or os.environ.get("OPEN_SANDBOX_ENDPOINT")
        self._client = client
        self.sandbox_id: Optional[str] = None
        self.context_id: Optional[str] = None

    def _build_default_client(self):
        try:
            from opensandbox import OpenSandboxClient  # type: ignore
        except ImportError as e:
            raise ImportError(
                "pip install opensandbox to use OpenSandboxRuntime without a "
                "caller-provided client. For tests, inject a stub via the "
                "`client=` constructor arg."
            ) from e
        kwargs = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._endpoint:
            kwargs["endpoint"] = self._endpoint
        return OpenSandboxClient(**kwargs)

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._build_default_client()
        return self._client

    def ensure_sandbox(self) -> str:
        """Create the sandbox if it hasn't been created yet. Idempotent."""
        if self.sandbox_id is None:
            resp = self.client.sandboxes.create(**self.spec.to_create_kwargs())
            self.sandbox_id = getattr(resp, "id", None) or (
                resp.get("id") if isinstance(resp, dict) else None
            )
            if not self.sandbox_id:
                raise RuntimeError(f"OpenSandbox create returned no id: {resp!r}")
        return self.sandbox_id

    def ensure_code_context(self, language: str = "python") -> str:
        """Create a stateful code-interpreter context. Variables persist across
        code.run() calls within the same context."""
        self.ensure_sandbox()
        if self.context_id is None:
            resp = self.client.code.create_context(
                sandbox_id=self.sandbox_id, language=language
            )
            self.context_id = getattr(resp, "id", None) or (
                resp.get("id") if isinstance(resp, dict) else None
            )
            if not self.context_id:
                raise RuntimeError(f"OpenSandbox create_context returned no id: {resp!r}")
        return self.context_id

    def execute_code(self, code: str, language: str = "python") -> ExecResult:
        """Run code in the persistent interpreter context. Variables persist."""
        self.ensure_code_context(language=language)
        resp = self.client.code.run(
            sandbox_id=self.sandbox_id,
            context_id=self.context_id,
            code=code,
        )
        return _normalize_code_response(resp)

    def execute_command(self, command: str) -> ExecResult:
        """Run a shell command in the sandbox."""
        self.ensure_sandbox()
        resp = self.client.command.run(sandbox_id=self.sandbox_id, command=command)
        return _normalize_command_response(resp)

    def file_read(self, path: str) -> ExecResult:
        self.ensure_sandbox()
        resp = self.client.files.read(sandbox_id=self.sandbox_id, path=path)
        return _normalize_file_response(resp)

    def file_write(self, path: str, content: str) -> ExecResult:
        self.ensure_sandbox()
        resp = self.client.files.write(
            sandbox_id=self.sandbox_id, path=path, content=content
        )
        return _normalize_file_response(resp)

    def renew(self, extend_seconds: int = 300) -> None:
        """Extend the sandbox timeout (long-running agents)."""
        self.ensure_sandbox()
        self.client.sandboxes.renew(
            sandbox_id=self.sandbox_id, extend_seconds=extend_seconds
        )

    def terminate(self) -> None:
        if self.sandbox_id is not None:
            try:
                self.client.sandboxes.terminate(sandbox_id=self.sandbox_id)
            except Exception:
                pass
            self.sandbox_id = None
            self.context_id = None

    def __enter__(self) -> "OpenSandboxRuntime":
        self.ensure_sandbox()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.terminate()


class ToolCallRouter:
    """Route unified trajectory tool_call events to OpenSandboxRuntime methods.

    The router normalizes common tool names (python.exec / shell.run / fs.*)
    so any adapter can emit semantically-named tool calls and have them land
    in the sandbox correctly. Unknown tool names raise ValueError — we do not
    silently execute what we don't understand.
    """

    CODE_NAMES = {"python.exec", "python_exec", "code.python", "run_python", "python"}
    SHELL_NAMES = {"shell.run", "bash.run", "run_command", "exec", "shell"}
    FILE_READ_NAMES = {"fs.read", "file.read", "read_file"}
    FILE_WRITE_NAMES = {"fs.write", "file.write", "write_file"}

    def __init__(self, runtime: OpenSandboxRuntime):
        self.runtime = runtime

    def dispatch(self, tool_call_content: dict) -> ExecResult:
        name = (tool_call_content.get("name") or "").lower()
        args = tool_call_content.get("arguments") or {}
        if isinstance(args, str):
            args = {"code": args} if name in self.CODE_NAMES else {"command": args}

        if name in self.CODE_NAMES:
            return self.runtime.execute_code(
                args.get("code", ""), language=args.get("language", "python")
            )
        if name in self.SHELL_NAMES:
            return self.runtime.execute_command(args.get("command", ""))
        if name in self.FILE_READ_NAMES:
            return self.runtime.file_read(args.get("path", ""))
        if name in self.FILE_WRITE_NAMES:
            return self.runtime.file_write(
                args.get("path", ""), args.get("content", "")
            )
        raise ValueError(f"ToolCallRouter: no OpenSandbox route for tool name {name!r}")


# ── Response normalizers ─────────────────────────────────────────────

def _get(resp: Any, *keys: str, default: Any = None) -> Any:
    """Read a field from either a dict or an object-with-attrs response."""
    for k in keys:
        if isinstance(resp, dict) and k in resp:
            return resp[k]
        if hasattr(resp, k):
            return getattr(resp, k)
    return default


def _normalize_code_response(resp: Any) -> ExecResult:
    return ExecResult(
        stdout=str(_get(resp, "stdout", "output", default="") or ""),
        stderr=str(_get(resp, "stderr", default="") or ""),
        return_value=_get(resp, "return_value", "result"),
        duration_ms=_get(resp, "duration_ms"),
        error=_get(resp, "error"),
    )


def _normalize_command_response(resp: Any) -> ExecResult:
    return ExecResult(
        stdout=str(_get(resp, "stdout", default="") or ""),
        stderr=str(_get(resp, "stderr", default="") or ""),
        exit_code=_get(resp, "exit_code", "returncode"),
        duration_ms=_get(resp, "duration_ms"),
        error=_get(resp, "error"),
    )


def _normalize_file_response(resp: Any) -> ExecResult:
    return ExecResult(
        stdout=str(_get(resp, "content", "data", default="") or ""),
        error=_get(resp, "error"),
    )


# ── Test stubs ──────────────────────────────────────────────────────

class _StubSandboxes:
    def __init__(self, parent):
        self.parent = parent

    def create(self, **kwargs):
        self.parent._last_create_kwargs = kwargs
        return {"id": "sbx-stub-1"}

    def renew(self, **kwargs):
        self.parent._renewed = True

    def terminate(self, **kwargs):
        self.parent._terminated = True


class _StubCode:
    def __init__(self, parent):
        self.parent = parent
        self._state = {}

    def create_context(self, **kwargs):
        return {"id": "ctx-stub-1"}

    def run(self, *, sandbox_id, context_id, code):
        # Tiny exec-in-dict simulation — useful for validating the routing,
        # not for real code running.
        try:
            exec(code, self._state)
            ret = self._state.get("__result__")
            return {"stdout": "", "return_value": ret, "duration_ms": 1}
        except Exception as e:
            return {"stderr": f"{type(e).__name__}: {e}", "error": str(e)}


class _StubCommand:
    def run(self, *, sandbox_id, command):
        if command == "echo hello":
            return {"stdout": "hello\n", "exit_code": 0, "duration_ms": 2}
        if command.startswith("false"):
            return {"stdout": "", "exit_code": 1, "duration_ms": 1}
        return {"stdout": f"(stub ran: {command})\n", "exit_code": 0, "duration_ms": 1}


class _StubFiles:
    def __init__(self):
        self._fs: dict[str, str] = {}

    def read(self, *, sandbox_id, path):
        if path not in self._fs:
            return {"content": "", "error": f"no such file: {path}"}
        return {"content": self._fs[path]}

    def write(self, *, sandbox_id, path, content):
        self._fs[path] = content
        return {"content": f"wrote {len(content)} bytes"}


class StubClient:
    """Tiny in-memory stand-in for opensandbox.OpenSandboxClient.

    Implements just enough surface area to exercise OpenSandboxRuntime +
    ToolCallRouter in tests without installing the library.
    """

    def __init__(self):
        self.sandboxes = _StubSandboxes(self)
        self.code = _StubCode(self)
        self.command = _StubCommand()
        self.files = _StubFiles()
        self._last_create_kwargs: Optional[dict] = None
        self._renewed: bool = False
        self._terminated: bool = False


def from_stub_client(spec: Optional[SandboxSpec] = None) -> OpenSandboxRuntime:
    """Convenience factory for tests — builds a runtime backed by StubClient."""
    return OpenSandboxRuntime(client=StubClient(), spec=spec)
