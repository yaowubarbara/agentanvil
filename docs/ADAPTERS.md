# Scaffold Adapter Guide

AgentAnvil ships eight scaffold adapters. Each one translates a scaffold's
native execution trace into the v0.1 Unified Trajectory Protocol (see
[TRAJECTORY_PROTOCOL.md](TRAJECTORY_PROTOCOL.md)).

## Adapter catalog

| Adapter | Native input | Status | Key design choice |
|---|---|---|---|
| `minimal` | raw Anthropic/OpenAI LLM call | ✅ stable | Single-turn baseline; no tool loop |
| `openai-agents-sdk` | `agents.Runner.run()` RunItems | ✅ stable | Defensive `getattr` mapping; tolerates SDK API drift |
| `langchain` | `AgentExecutor.invoke()` result | ✅ stable | Reads `intermediate_steps` → paired TOOL_CALL / TOOL_RESULT |
| `claude-code` | `claude -p ... --output-format stream-json` | ✅ stable | `from_stream()` replays recorded fixtures without the binary |
| `openhands` | OpenHands Action/Observation stream | ✅ P2+ | Pair tool calls via object identity when no call_id |
| `autogen` | AutoGen ChatMessage types | ✅ P2+ | Handoff-message aware; captures `stop_reason` |
| `crewai` | `Crew.kickoff()` CrewOutput | ✅ P2+ | Per-task agent-role captured in event.meta |
| `langgraph` | streamed state-graph values | ✅ P2+ | Dedupe via message.id across state snapshots |
| `llamaindex` | legacy ReActAgent + v0.12 AgentWorkflow | ✅ P2+ | Dual-mode; auto-detect via class name |

## Authoring a new adapter

An adapter is just a subclass of `AnvilAgent` that implements `run(task) -> Trajectory`.

### 1. Minimum viable shape

```python
from agentanvil.agent import AnvilAgent, AnvilTask
from agentanvil.trajectory import EventKind, Trajectory

class MyScaffoldAdapter(AnvilAgent):
    scaffold_name = "my-scaffold"

    def __init__(self, scaffold_instance):
        self.scaffold = scaffold_instance

    def run(self, task: AnvilTask) -> Trajectory:
        traj = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        traj.meta["protocol_version"] = "0.1"
        obs = task.initial_observation()
        traj.emit(EventKind.OBSERVATION, obs)

        try:
            # 1. drive the scaffold
            result = self.scaffold.run(obs["text"])
            # 2. map scaffold's native events to unified protocol
            for native_event in result.events:
                kind, content = self._classify(native_event)
                traj.emit(kind, content)
            # 3. attach final answer
            traj.emit(EventKind.FINAL_ANSWER, result.final_text)
        except Exception as e:
            traj.emit(EventKind.ERROR, {"type": type(e).__name__, "message": str(e)})
        traj.finish()
        return traj

    def _classify(self, native_event):
        # scaffold-specific translation logic
        ...
```

### 2. Conformance contract (MUST pass)

Every adapter's output must satisfy the eight rules in TRAJECTORY_PROTOCOL.md §5:

1. `events` is non-empty
2. First event is `observation`
3. Last non-reward event is `final_answer` or `error`
4. At most one `final_answer` and at most one `error`
5. `step` is contiguous and monotonic
6. `ts` is non-decreasing
7. Round-trips through `json.dumps`/`json.loads`
8. Every `tool_result` pairs with a preceding `tool_call`

Validate during development:

```python
from agentanvil.schema import validate
issues = validate(traj)
assert not issues, f"adapter violated protocol: {[str(i) for i in issues]}"
```

### 3. Testability pattern — the `from_*` helper

Every shipped adapter exposes a dependency-free helper that constructs a
trajectory from a captured fixture. This lets tests run without installing
any scaffold:

```python
# agentanvil/adapter/my_scaffold.py
def from_events(task_id: str, events: list) -> Trajectory:
    class _T(AnvilTask):
        def __init__(self, tid): self.task_id = tid
        def initial_observation(self): return {"text": "(replayed)"}
    adapter = MyScaffoldAdapter(scaffold_stub_with(events))
    return adapter.run(_T(task_id))
```

The `from_*` helpers collectively drive our 5/5 new-adapter conformance
suite without any pip installs beyond agentanvil itself.

### 4. Defensive mapping for SDK drift

Scaffold SDKs change. Our adapters degrade gracefully:

- Map by **class name substring**, not exact type import (`"ToolCall" in cls`)
- Use `getattr(x, attr, fallback)` not `x.attr`
- Unknown event kinds go into `trajectory.meta.unhandled` (not raised as errors)
- Tool-call IDs are OPTIONAL; pair by order if the SDK omits them

This is why the OpenAI Agents SDK adapter survives 0.1 → 0.2 → 0.3 without
constant rewrites.

## Reviewing an adapter PR

Checklist for merging a new adapter:

- [ ] `scaffold_name` is lowercase kebab-case, unique
- [ ] `run()` always emits an initial OBSERVATION and exactly one terminal event
- [ ] All event content is JSON-serializable (tests exercise `json.dumps`)
- [ ] Tool calls carry `name`, `arguments`, and `call_id` when scaffold provides it
- [ ] Error paths emit an ERROR event rather than raising out of `run()`
- [ ] A `from_*` helper exists for dep-free testing
- [ ] `tests/test_new_adapters_conformance.py` has a fixture test
- [ ] README table updated with status + key design choice

## See also

- [TRAJECTORY_PROTOCOL.md](TRAJECTORY_PROTOCOL.md) — the wire contract every adapter lives by
- [VERIFIERS.md](VERIFIERS.md) — how scoring integrates with adapter output
- [../agentanvil/adapter/claude_code.py](../agentanvil/adapter/claude_code.py) — reference implementation using CLI subprocess + stream-json
