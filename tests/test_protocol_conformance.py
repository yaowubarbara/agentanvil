"""
Cross-scaffold conformance tests.

Builds a synthetic trajectory for each supported adapter (via stubs, so these
tests run without any API keys or scaffold installs) and validates each
against the v0.1 schema.

Also covers negative cases: the validator must flag each MUST-rule violation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentanvil import AnvilAgent, AnvilTask
from agentanvil.trajectory import EventKind, Trajectory
from agentanvil.schema import is_compliant, validate, PROTOCOL_VERSION
from agentanvil.adapter.langchain import from_callable as lc_from_callable
from agentanvil.adapter.claude_code import ClaudeCodeAdapter


class _Task(AnvilTask):
    def __init__(self, task_id: str, prompt: str = "count dots"):
        self.task_id = task_id
        self._prompt = prompt

    def initial_observation(self) -> dict:
        return {"text": self._prompt}


def _synth_minimal() -> Trajectory:
    """Minimal adapter output: obs + final."""
    t = Trajectory(task_id="suite/m_000", scaffold="minimal")
    t.meta["protocol_version"] = PROTOCOL_VERSION
    t.emit(EventKind.OBSERVATION, {"text": "count dots"})
    t.emit(EventKind.FINAL_ANSWER, "ANSWER: 3")
    t.finish()
    return t


def _synth_openai_agents() -> Trajectory:
    """OpenAI Agents SDK-shaped trajectory with one tool round-trip."""
    t = Trajectory(task_id="suite/oa_000", scaffold="openai-agents-sdk")
    t.meta["protocol_version"] = PROTOCOL_VERSION
    t.emit(EventKind.OBSERVATION, {"text": "count dots"})
    t.emit(EventKind.THOUGHT, {"text": "I need to use the grid counter tool."})
    t.emit(
        EventKind.TOOL_CALL,
        {"name": "count_in_region", "arguments": {"region": "interior"}, "call_id": "call_1"},
        sdk_item="ToolCallItem",
    )
    t.emit(
        EventKind.TOOL_RESULT,
        {"call_id": "call_1", "output": "3"},
        sdk_item="ToolOutputItem",
    )
    t.emit(EventKind.FINAL_ANSWER, "ANSWER: 3")
    t.finish()
    return t


def _synth_langchain() -> Trajectory:
    """LangChain-shaped trajectory via the from_callable escape hatch."""

    class _FakeAgentAction:
        tool = "count_tool"
        tool_input = {"curve": "closed_rose"}
        tool_call_id = "lc_1"
        log = "decided to call count_tool"

    def fn(_prompt: str):
        return {
            "output": "ANSWER: 3",
            "intermediate_steps": [(_FakeAgentAction(), "3")],
        }

    adapter = lc_from_callable(fn)
    return adapter.run(_Task("suite/lc_000"))


def _synth_claude_code() -> Trajectory:
    """Claude Code: parse a recorded stream-json fixture into a trajectory."""
    fixture = Path(__file__).parent / "fixtures" / "claude_code_sample.jsonl"
    return ClaudeCodeAdapter.from_stream(fixture, task_id="suite/cc_000")


def _all_good(name, traj):
    issues = validate(traj)
    assert not issues, f"{name} failed conformance: {[str(i) for i in issues]}"
    assert is_compliant(traj)
    # also round-trip through JSON
    json.loads(json.dumps(traj.to_json()))


def test_four_scaffolds_conform():
    _all_good("minimal", _synth_minimal())
    _all_good("openai-agents-sdk", _synth_openai_agents())
    _all_good("langchain", _synth_langchain())
    _all_good("claude-code", _synth_claude_code())


def test_claude_code_stream_mapping():
    """Spot-check the stream-json → unified events mapping."""
    traj = _synth_claude_code()
    kinds = [e.kind.value for e in traj.events]
    # Expected shape from fixture:
    # [observation, thought(thinking), tool_call, tool_result, thought(text), final_answer]
    assert kinds[0] == "observation"
    assert "thought" in kinds
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    assert kinds[-1] == "final_answer"
    # Call ID propagation: tool_call.call_id must equal tool_result.call_id
    tc = next(e for e in traj.events if e.kind == EventKind.TOOL_CALL)
    tr = next(e for e in traj.events if e.kind == EventKind.TOOL_RESULT)
    assert tc.content["call_id"] == tr.content["call_id"] == "toolu_01"
    # Final answer must be strict-parseable by Jordan Count verifier
    from agentanvil.verifier.jordan_count import JordanCountVerifier
    assert JordanCountVerifier().parse(traj.final_answer()) == 3
    # Session ID captured from system/init event
    assert traj.meta.get("claude_session_id") == "session_abc123"


def test_negative_empty_events():
    t = Trajectory(task_id="x", scaffold="bad")
    t.finish()
    issues = validate(t)
    rules = {i.rule for i in issues}
    assert "MUST-1" in rules


def test_negative_missing_initial_observation():
    t = Trajectory(task_id="x", scaffold="bad")
    t.emit(EventKind.FINAL_ANSWER, "ANSWER: 1")
    issues = validate(t)
    assert any(i.rule == "MUST-2" for i in issues)


def test_negative_non_terminal_last():
    t = Trajectory(task_id="x", scaffold="bad")
    t.emit(EventKind.OBSERVATION, {"text": "hi"})
    t.emit(EventKind.THOUGHT, {"text": "hmm"})
    issues = validate(t)
    assert any(i.rule == "MUST-3" for i in issues)


def test_negative_both_final_and_error():
    t = Trajectory(task_id="x", scaffold="bad")
    t.emit(EventKind.OBSERVATION, {"text": "hi"})
    t.emit(EventKind.FINAL_ANSWER, "ANSWER: 1")
    t.emit(EventKind.ERROR, {"type": "X", "message": "y"})
    issues = validate(t)
    assert any(i.rule == "MUST-4" for i in issues)


def test_negative_step_index_mismatch():
    data = {
        "trajectory_id": "x",
        "task_id": "x",
        "scaffold": "bad",
        "started_at": 0,
        "finished_at": 1,
        "meta": {},
        "events": [
            {"kind": "observation", "content": {"text": "hi"}, "step": 0, "ts": 0, "meta": {}},
            {"kind": "final_answer", "content": "ok", "step": 5, "ts": 1, "meta": {}},
        ],
    }
    issues = validate(data)
    assert any(i.rule == "MUST-5" for i in issues)


def test_negative_ts_decreasing():
    data = {
        "trajectory_id": "x",
        "task_id": "x",
        "scaffold": "bad",
        "started_at": 0,
        "finished_at": 1,
        "meta": {},
        "events": [
            {"kind": "observation", "content": {"text": "hi"}, "step": 0, "ts": 5.0, "meta": {}},
            {"kind": "final_answer", "content": "ok", "step": 1, "ts": 4.0, "meta": {}},
        ],
    }
    issues = validate(data)
    assert any(i.rule == "MUST-6" for i in issues)


def test_negative_tool_result_without_call():
    t = Trajectory(task_id="x", scaffold="bad")
    t.emit(EventKind.OBSERVATION, {"text": "hi"})
    t.emit(EventKind.TOOL_RESULT, {"output": "x"})
    t.emit(EventKind.FINAL_ANSWER, "ok")
    issues = validate(t)
    assert any(i.rule == "MUST-8" for i in issues)


def test_negative_tool_result_wrong_call_id():
    t = Trajectory(task_id="x", scaffold="bad")
    t.emit(EventKind.OBSERVATION, {"text": "hi"})
    t.emit(EventKind.TOOL_CALL, {"name": "f", "arguments": {}, "call_id": "A"})
    t.emit(EventKind.TOOL_RESULT, {"output": "x", "call_id": "B"})
    t.emit(EventKind.FINAL_ANSWER, "ok")
    issues = validate(t)
    assert any(i.rule == "MUST-8" for i in issues)


def test_positive_paired_tool_calls():
    t = Trajectory(task_id="x", scaffold="good")
    t.emit(EventKind.OBSERVATION, {"text": "hi"})
    t.emit(EventKind.TOOL_CALL, {"name": "f", "arguments": {}, "call_id": "A"})
    t.emit(EventKind.TOOL_RESULT, {"output": "x", "call_id": "A"})
    t.emit(EventKind.TOOL_CALL, {"name": "g", "arguments": {}, "call_id": "B"})
    t.emit(EventKind.TOOL_RESULT, {"output": "y", "call_id": "B"})
    t.emit(EventKind.FINAL_ANSWER, "ok")
    assert is_compliant(t)


if __name__ == "__main__":
    # Lightweight runner without pytest dependency
    tests = [fn for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn)]
    passed = 0
    failed: list[tuple[str, str]] = []
    for fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            failed.append((fn.__name__, str(e)))
            print(f"  ✗ {fn.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    if failed:
        sys.exit(1)
