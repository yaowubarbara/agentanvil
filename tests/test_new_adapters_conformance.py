"""
Conformance tests for Phase 2+ adapters (OpenHands / AutoGen / CrewAI /
LangGraph / LlamaIndex).

Each test builds a scaffold-shaped fixture in memory and feeds it through
the corresponding adapter's dep-free `from_*` helper, then validates the
resulting trajectory against the v0.1 schema.

These fixtures are intentionally NOT real scaffold objects — they're
lightweight stand-ins with the attribute shape the adapter expects. This
keeps the test suite fast and independent of 5 different pip installs.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentanvil.schema import is_compliant, validate
from agentanvil.trajectory import EventKind


def _assert_compliant(name, traj):
    issues = validate(traj)
    assert not issues, f"{name} failed conformance: {[str(i) for i in issues]}"
    assert is_compliant(traj)
    kinds = [e.kind.value for e in traj.events]
    assert kinds[0] == "observation"
    assert kinds[-1] in ("final_answer", "error", "reward")


def test_openhands_adapter_conforms():
    from agentanvil.adapter.openhands import from_events

    class MessageAction:
        def __init__(self, content, source="agent"):
            self.content = content
            self.source = source

    class CmdRunAction:
        def __init__(self, command):
            self.command = command

    class CmdOutputObservation:
        def __init__(self, content, exit_code=0):
            self.content = content
            self.exit_code = exit_code

    class AgentFinishAction:
        def __init__(self, outputs):
            self.outputs = outputs

    events = [
        MessageAction("I need to list the directory first.", source="agent"),
        CmdRunAction("ls -la"),
        CmdOutputObservation("total 0\ndrwxr-xr-x 2 user user 40 ..", exit_code=0),
        MessageAction("Now I'll write the answer.", source="agent"),
        AgentFinishAction("ANSWER: 3"),
    ]
    traj = from_events("suite/oh_000", events)
    _assert_compliant("openhands", traj)
    assert traj.final_answer() == "ANSWER: 3"
    kinds = [e.kind.value for e in traj.events]
    assert "tool_call" in kinds and "tool_result" in kinds


def test_autogen_adapter_conforms():
    from agentanvil.adapter.autogen import from_messages

    class TextMessage:
        def __init__(self, content, source):
            self.content = content
            self.source = source

    class ToolCallRequestEvent:
        class _Call:
            def __init__(self, name, arguments, id):
                self.name = name
                self.arguments = arguments
                self.id = id

        def __init__(self, calls):
            self.content = calls

    class ToolCallExecutionEvent:
        class _Result:
            def __init__(self, call_id, content):
                self.call_id = call_id
                self.content = content
                self.is_error = False

        def __init__(self, results):
            self.content = results

    messages = [
        TextMessage("I'll call the counter tool.", source="assistant"),
        ToolCallRequestEvent([ToolCallRequestEvent._Call("count", {"x": 1}, "ag-1")]),
        ToolCallExecutionEvent([ToolCallExecutionEvent._Result("ag-1", "3")]),
        TextMessage("ANSWER: 3", source="assistant"),
    ]
    traj = from_messages("suite/ag_000", messages, stop_reason="stop")
    _assert_compliant("autogen", traj)
    assert "tool_call" in [e.kind.value for e in traj.events]


def test_crewai_adapter_conforms():
    from agentanvil.adapter.crewai import from_tasks_output

    class ToolUsage:
        def __init__(self, tool, tool_input, result, id):
            self.tool_name = tool
            self.arguments = tool_input
            self.result = result
            self.id = id

    class TaskOutput:
        def __init__(self, agent, description, raw, tool_calls):
            self.agent = agent
            self.description = description
            self.raw = raw
            self.tool_calls = tool_calls

    tasks_output = [
        TaskOutput(
            agent="Analyst",
            description="Count the dots",
            raw="3 dots are inside",
            tool_calls=[ToolUsage("count_dots", {"curve": "rose"}, "3", "crew-1")],
        )
    ]
    traj = from_tasks_output("suite/crew_000", tasks_output, final_raw="ANSWER: 3")
    _assert_compliant("crewai", traj)
    assert traj.final_answer() == "ANSWER: 3"
    thought_events = [e for e in traj.events if e.kind == EventKind.THOUGHT]
    assert any(e.meta.get("agent") == "Analyst" for e in thought_events)


def test_langgraph_adapter_conforms():
    from agentanvil.adapter.langgraph import from_states

    states = [
        {"__node__": "planner", "messages": [
            {"id": "u1", "role": "user", "content": "count dots"},
            {"id": "a1", "role": "assistant", "content": "I'll use the counter",
             "tool_calls": [{"name": "count", "args": {"curve": "rose"}, "id": "lg-1"}]},
        ]},
        {"__node__": "tools", "messages": [
            {"id": "u1", "role": "user", "content": "count dots"},
            {"id": "a1", "role": "assistant", "content": "I'll use the counter",
             "tool_calls": [{"name": "count", "args": {"curve": "rose"}, "id": "lg-1"}]},
            {"id": "t1", "role": "tool", "content": "3", "tool_call_id": "lg-1"},
        ]},
        {"__node__": "responder", "messages": [
            {"id": "u1", "role": "user", "content": "count dots"},
            {"id": "a1", "role": "assistant", "content": "I'll use the counter",
             "tool_calls": [{"name": "count", "args": {"curve": "rose"}, "id": "lg-1"}]},
            {"id": "t1", "role": "tool", "content": "3", "tool_call_id": "lg-1"},
            {"id": "a2", "role": "assistant", "content": "ANSWER: 3"},
        ]},
    ]
    traj = from_states("suite/lg_000", states)
    _assert_compliant("langgraph", traj)
    assert traj.final_answer() == "ANSWER: 3"
    kinds = [e.kind.value for e in traj.events]
    assert "tool_call" in kinds and "tool_result" in kinds


def test_llamaindex_legacy_adapter_conforms():
    from agentanvil.adapter.llamaindex import LlamaIndexAdapter
    from agentanvil.agent import AnvilTask

    class _Src:
        def __init__(self, tool_name, raw_in, raw_out, tool_id):
            self.tool_name = tool_name
            self.raw_input = raw_in
            self.raw_output = raw_out
            self.tool_id = tool_id

    class _Agent:
        class _Response:
            def __init__(self, response, sources):
                self.response = response
                self.sources = sources

        def chat(self, prompt):
            return _Agent._Response(
                "ANSWER: 3",
                [_Src("count_dots", {"curve": "rose"}, "3", "li-1")],
            )

    class _Task(AnvilTask):
        task_id = "suite/li_000"

        def initial_observation(self) -> dict:
            return {"text": "count dots"}

    adapter = LlamaIndexAdapter(agent=_Agent(), mode="legacy")
    traj = adapter.run(_Task())
    _assert_compliant("llamaindex-legacy", traj)
    kinds = [e.kind.value for e in traj.events]
    assert "tool_call" in kinds and "tool_result" in kinds


if __name__ == "__main__":
    tests = [fn for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn)]
    passed = 0
    failed = []
    for fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            failed.append((fn.__name__, str(e)))
            print(f"  ✗ {fn.__name__}: {e}")
        except Exception as e:
            failed.append((fn.__name__, f"{type(e).__name__}: {e}"))
            print(f"  ✗ {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    if failed:
        sys.exit(1)
