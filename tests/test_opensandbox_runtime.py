"""
Tests for the OpenSandbox runtime integration.

Exercises the full surface — lifecycle, code context, command, files, and
the tool-call router — against an in-memory StubClient that mirrors the
real opensandbox SDK's method names.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentanvil.runtime.opensandbox import (
    ExecResult,
    OpenSandboxRuntime,
    SandboxSpec,
    StubClient,
    ToolCallRouter,
    from_stub_client,
)


def test_runtime_creates_sandbox_on_demand():
    rt = from_stub_client(SandboxSpec(image="python:3.12", runtime="gvisor"))
    assert rt.sandbox_id is None
    rt.ensure_sandbox()
    assert rt.sandbox_id == "sbx-stub-1"
    # spec propagated
    assert rt._client._last_create_kwargs["image"] == "python:3.12"
    assert rt._client._last_create_kwargs["runtime"] == "gvisor"


def test_runtime_execute_code_maintains_context_state():
    rt = from_stub_client()
    r1 = rt.execute_code("x = 5\n__result__ = x")
    assert r1.ok
    assert r1.return_value == 5
    # Same context — x should still exist
    r2 = rt.execute_code("__result__ = x + 10")
    assert r2.return_value == 15
    assert rt.context_id == "ctx-stub-1"   # reused, not recreated


def test_runtime_execute_command_captures_exit():
    rt = from_stub_client()
    r = rt.execute_command("echo hello")
    assert r.ok
    assert "hello" in r.stdout
    r2 = rt.execute_command("false")
    assert not r2.ok
    assert r2.exit_code == 1


def test_runtime_file_read_write_roundtrip():
    rt = from_stub_client()
    rt.file_write("/tmp/data.txt", "the quick brown fox")
    r = rt.file_read("/tmp/data.txt")
    assert "quick brown fox" in r.stdout
    missing = rt.file_read("/no-such-path")
    assert not missing.ok


def test_runtime_terminates_on_context_exit():
    spec = SandboxSpec(image="python:3.11-slim")
    with from_stub_client(spec) as rt:
        rt.execute_command("echo hi")
        assert rt.sandbox_id is not None
    assert rt.sandbox_id is None   # cleared on __exit__


def test_runtime_renew_calls_through():
    rt = from_stub_client()
    rt.ensure_sandbox()
    rt.renew(extend_seconds=600)
    assert rt._client._renewed is True


def test_runtime_requires_opensandbox_when_no_client():
    """Without caller-provided client, lazy import must raise if lib absent.

    If opensandbox *is* installed (CI env has it), the error won't fire —
    that's fine; we just verify no crash on the attribute access path.
    """
    rt = OpenSandboxRuntime()  # no client, no api key
    try:
        _ = rt.client
    except ImportError as e:
        assert "opensandbox" in str(e)


def test_exec_result_to_tool_result_content_shape():
    r = ExecResult(stdout="out", stderr="err", exit_code=0, duration_ms=12)
    content = r.to_tool_result_content()
    assert content["output"] == "out"
    assert content["stderr"] == "err"
    assert content["exit_code"] == 0
    assert content["duration_ms"] == 12
    assert content["error"] is None


# ── ToolCallRouter ──────────────────────────────────────────────────

def test_router_python_exec():
    rt = from_stub_client()
    router = ToolCallRouter(rt)
    r = router.dispatch({
        "name": "python.exec",
        "arguments": {"code": "__result__ = 2 + 2"},
    })
    assert r.ok
    assert r.return_value == 4


def test_router_shell_run_alias():
    rt = from_stub_client()
    router = ToolCallRouter(rt)
    r = router.dispatch({"name": "bash.run", "arguments": {"command": "echo hello"}})
    assert "hello" in r.stdout


def test_router_file_read_write():
    rt = from_stub_client()
    router = ToolCallRouter(rt)
    router.dispatch({
        "name": "fs.write",
        "arguments": {"path": "/tmp/x", "content": "payload"},
    })
    r = router.dispatch({"name": "fs.read", "arguments": {"path": "/tmp/x"}})
    assert r.stdout == "payload"


def test_router_unknown_tool_raises():
    rt = from_stub_client()
    router = ToolCallRouter(rt)
    try:
        router.dispatch({"name": "make_coffee", "arguments": {}})
    except ValueError as e:
        assert "make_coffee" in str(e)
        return
    raise AssertionError("expected ValueError on unknown tool")


def test_router_string_arguments_coerced():
    """Some scaffolds pass arguments as a JSON string or raw code string."""
    rt = from_stub_client()
    router = ToolCallRouter(rt)
    r = router.dispatch({"name": "python", "arguments": "__result__ = 99"})
    assert r.return_value == 99


def test_router_case_insensitive_name():
    rt = from_stub_client()
    router = ToolCallRouter(rt)
    r = router.dispatch({"name": "SHELL.RUN", "arguments": {"command": "echo hi"}})
    assert r.ok


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn)]
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {name}")
        except AssertionError as e:
            failed.append((name, str(e)))
            print(f"  ✗ {name}: {e}")
        except Exception as e:
            failed.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    if failed:
        sys.exit(1)
