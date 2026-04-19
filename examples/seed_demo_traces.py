"""
Seed demo traces for the dashboard — ALL 8 scaffolds on the SAME task.

Each scaffold produces a realistic-shaped trajectory on suite/jc_000 (Jordan
Count, gold=3). Behaviors are crafted to show the *kinds* of variation real
scaffolds produce:

  claude-code          full tool-use loop (thinking → tool → result → final)  → ANSWER: 3  ✓
  openai-agents-sdk    tool call via SDK item stream                          → ANSWER: 3  ✓
  langchain            AgentExecutor intermediate_steps loop                  → ANSWER: 3  ✓
  openhands            Action/Observation event stream                        → ANSWER: 3  ✓
  autogen              multi-agent ChatMessage with handoff                   → ANSWER: 4  ✗ overcount
  crewai               role-based (Analyst → Verifier)                        → ANSWER: 3  ✓
  langgraph            state-graph with tool node                             → ANSWER: 2  ✗ undercount
  llamaindex           legacy ReActAgent sources                              → ANSWER: 3  ✓
  minimal              naked LLM, no tools, just guesses                      → ANSWER: 4  ✗ overcount (baseline)
  minimal (2)          second attempt, format violation                       → (parse fail) ✗

Gives the UI:
  - 10 trajectories across 9 distinct scaffolds
  - Accuracy bars with range (60% success rate overall)
  - Heatmap dense enough to see patterns
  - Diff UI has lots of interesting pairs to compare
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentanvil import AnvilAgent, AnvilTask, run_one
from agentanvil.adapter.claude_code import ClaudeCodeAdapter
from agentanvil.adapter.openhands import from_events as oh_from_events
from agentanvil.adapter.autogen import from_messages as ag_from_messages
from agentanvil.adapter.crewai import from_tasks_output as crew_from_tasks
from agentanvil.adapter.langgraph import from_states as lg_from_states
from agentanvil.adapter.langchain import from_callable as lc_from_callable
from agentanvil.trajectory import EventKind, Trajectory
from agentanvil.trace.local import LocalJsonlSink
from agentanvil.verifier.jordan_count import JordanCountTask, JordanCountVerifier


TASK_ID = "suite/jc_000"
GOLD = 3
TRACES_PATH = Path(__file__).resolve().parents[1] / "traces" / "traces.jsonl"
FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "claude_code_sample.jsonl"


# ── Adapter factory: each returns an AnvilAgent that produces a specific
# scaffold's trajectory shape on ANY task. Internally they synthesize
# fixture-shaped inputs and feed them through the real adapter's from_*
# helper, so the resulting trajectory is 100% real v0.1 protocol.

def _claude_code_correct(task):
    traj = ClaudeCodeAdapter.from_stream(FIXTURE, task_id=task.task_id)
    # Overwrite the first obs with the actual task obs
    obs_ev = traj.events[0]
    obs_ev.content = task.initial_observation()
    return traj


def _openai_agents_correct(task):
    t = Trajectory(task_id=task.task_id, scaffold="openai-agents-sdk")
    t.meta["protocol_version"] = "0.1"
    t.emit(EventKind.OBSERVATION, task.initial_observation())
    t.emit(EventKind.THOUGHT, {"text": "I'll use the dot-counting tool with crossing-number."},
           sdk_item="ReasoningItem")
    t.emit(EventKind.TOOL_CALL,
           {"name": "count_dots", "arguments": {"method": "crossing_number"}, "call_id": "oa_tc_1"},
           sdk_item="ToolCallItem")
    t.emit(EventKind.TOOL_RESULT, {"call_id": "oa_tc_1", "output": "3"}, sdk_item="ToolOutputItem")
    t.emit(EventKind.FINAL_ANSWER, "ANSWER: 3")
    t.finish()
    return t


def _langchain_correct(task):
    def fake_exec(_prompt):
        class _Action:
            tool = "count_dots"
            tool_input = {"curve": "closed_rose"}
            tool_call_id = "lc_1"
            log = "Invoking: count_dots"
        return {
            "output": "ANSWER: 3",
            "intermediate_steps": [(_Action(), "3")],
        }
    return lc_from_callable(fake_exec).run(task)


def _openhands_correct(task):
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
        MessageAction("I'll spawn a Python script to ray-cast from each dot.", source="agent"),
        CmdRunAction("python3 -c 'from jordan import count_inside; print(count_inside())'"),
        CmdOutputObservation("3\n", exit_code=0),
        MessageAction("Got 3. Emitting canonical answer.", source="agent"),
        AgentFinishAction("ANSWER: 3"),
    ]
    traj = oh_from_events(task.task_id, events)
    traj.events[0].content = task.initial_observation()
    return traj


def _autogen_overcount(task):
    """AutoGen multi-agent chat with a handoff that overcounts."""
    class TextMessage:
        def __init__(self, content, source):
            self.content = content
            self.source = source
    class ToolCallRequestEvent:
        class _Call:
            def __init__(self, name, arguments, id_):
                self.name = name
                self.arguments = arguments
                self.id = id_
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
    class HandoffMessage:
        def __init__(self, source, target):
            self.source = source
            self.target = target
    msgs = [
        TextMessage("Let me estimate by eye first.", source="Planner"),
        HandoffMessage(source="Planner", target="Counter"),
        TextMessage("I see 4 dots near the interior region.", source="Counter"),
        ToolCallRequestEvent([ToolCallRequestEvent._Call("boundary_check", {"dots": [1, 2, 4, 8]}, "ag_1")]),
        ToolCallExecutionEvent([ToolCallExecutionEvent._Result("ag_1", "4 boundary-adjacent")]),
        TextMessage("ANSWER: 4", source="Counter"),
    ]
    return ag_from_messages(task.task_id, msgs, stop_reason="stop")


def _crewai_correct(task):
    class ToolUsage:
        def __init__(self, tool, tool_input, result, id_):
            self.tool_name = tool
            self.arguments = tool_input
            self.result = result
            self.id = id_
    class TaskOutput:
        def __init__(self, agent, description, raw, tool_calls):
            self.agent = agent
            self.description = description
            self.raw = raw
            self.tool_calls = tool_calls
    tasks_output = [
        TaskOutput(
            agent="Analyst",
            description="Identify region of interest",
            raw="closed rose curve with 8 dots",
            tool_calls=[],
        ),
        TaskOutput(
            agent="Counter",
            description="Count dots strictly inside",
            raw="3 inside via ray casting",
            tool_calls=[ToolUsage("ray_cast", {"origin": "each_dot"}, "3", "crew_1")],
        ),
    ]
    return crew_from_tasks(task.task_id, tasks_output, final_raw="ANSWER: 3")


def _langgraph_undercount(task):
    """LangGraph flow where the tool-less node undercounts because it skips step."""
    states = [
        {"__node__": "planner", "messages": [
            {"id": "u1", "role": "user", "content": "count dots inside"},
            {"id": "a1", "role": "assistant",
             "content": "I'll try approximate boundary inspection first.",
             "tool_calls": [{"name": "approx_boundary", "args": {}, "id": "lg_1"}]},
        ]},
        {"__node__": "tools", "messages": [
            {"id": "u1", "role": "user", "content": "count dots inside"},
            {"id": "a1", "role": "assistant",
             "content": "I'll try approximate boundary inspection first.",
             "tool_calls": [{"name": "approx_boundary", "args": {}, "id": "lg_1"}]},
            {"id": "t1", "role": "tool", "content": "2 obviously inside (fast estimate)",
             "tool_call_id": "lg_1"},
        ]},
        {"__node__": "responder", "messages": [
            {"id": "u1", "role": "user", "content": "count dots inside"},
            {"id": "a1", "role": "assistant",
             "content": "I'll try approximate boundary inspection first.",
             "tool_calls": [{"name": "approx_boundary", "args": {}, "id": "lg_1"}]},
            {"id": "t1", "role": "tool", "content": "2 obviously inside (fast estimate)",
             "tool_call_id": "lg_1"},
            {"id": "a2", "role": "assistant", "content": "ANSWER: 2"},
        ]},
    ]
    return lg_from_states(task.task_id, states)


def _llamaindex_correct(task):
    from agentanvil.adapter.llamaindex import LlamaIndexAdapter

    class _Src:
        def __init__(self, name, raw_in, raw_out, tid):
            self.tool_name = name
            self.raw_input = raw_in
            self.raw_output = raw_out
            self.tool_id = tid

    class _Resp:
        def __init__(self, response, sources):
            self.response = response
            self.sources = sources

    class _Agent:
        def chat(self, prompt):
            return _Resp(
                "ANSWER: 3",
                [_Src("count_dots", {"curve": "rose"}, "3", "li_1")],
            )

    return LlamaIndexAdapter(agent=_Agent(), mode="legacy").run(task)


class _MinimalOvercount(AnvilAgent):
    scaffold_name = "minimal"

    def run(self, task):
        t = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        t.meta["protocol_version"] = "0.1"
        t.emit(EventKind.OBSERVATION, task.initial_observation())
        t.emit(EventKind.THOUGHT,
               {"text": "Eyeballing it — boundary dots look inside to me. Guessing 4."})
        t.emit(EventKind.FINAL_ANSWER, "ANSWER: 4", model="stub", provider="stub")
        t.finish()
        return t


class _MinimalFormatFail(AnvilAgent):
    scaffold_name = "minimal"

    def run(self, task):
        t = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        t.meta["protocol_version"] = "0.1"
        t.emit(EventKind.OBSERVATION, task.initial_observation())
        t.emit(EventKind.FINAL_ANSWER,
               "I think there are three dots inside the curve based on my visual inspection.",
               model="stub", provider="stub")
        t.finish()
        return t


class _CallableAgent(AnvilAgent):
    def __init__(self, scaffold_name, fn):
        self.scaffold_name = scaffold_name
        self._fn = fn

    def run(self, task):
        return self._fn(task)


def main():
    TRACES_PATH.unlink(missing_ok=True)
    TRACES_PATH.parent.mkdir(parents=True, exist_ok=True)
    sink = LocalJsonlSink(TRACES_PATH)
    verifier = JordanCountVerifier()

    task = JordanCountTask(task_id=TASK_ID, image_path=None, gold_count=GOLD)

    seeded = [
        ("claude-code",          _CallableAgent("claude-code",           _claude_code_correct)),
        ("openai-agents-sdk",    _CallableAgent("openai-agents-sdk",     _openai_agents_correct)),
        ("langchain",            _CallableAgent("langchain",             _langchain_correct)),
        ("openhands",            _CallableAgent("openhands",             _openhands_correct)),
        ("autogen",              _CallableAgent("autogen",               _autogen_overcount)),
        ("crewai",               _CallableAgent("crewai",                _crewai_correct)),
        ("langgraph",            _CallableAgent("langgraph",             _langgraph_undercount)),
        ("llamaindex",           _CallableAgent("llamaindex",            _llamaindex_correct)),
        ("minimal (overcount)",  _MinimalOvercount()),
        ("minimal (no format)",  _MinimalFormatFail()),
    ]

    print(f"Seeding {TRACES_PATH}")
    for label, agent in seeded:
        traj, result = run_one(agent, task, verifier, [sink])
        mark = "✓" if result.correct else "✗"
        d = result.meta.get("direction")
        dir_str = f"dir={d}" if d else ""
        print(f"  {mark} {label:<24} parsed={result.parsed!s:<6} reward={result.reward} {dir_str}")

    correct = sum(1 for r in Path(TRACES_PATH).read_text().splitlines() if '"correct": true' in r)
    total = len([l for l in Path(TRACES_PATH).read_text().splitlines() if l.strip()])
    print(f"\nTotal: {total} trajectories, {correct} correct ({correct/total:.0%})")


if __name__ == "__main__":
    main()
