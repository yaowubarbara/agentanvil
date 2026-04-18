# AgentAnvil

**Scaffold-agnostic Agent training & evaluation harness.**

Plug any agent scaffold (OpenAI Agents SDK, Claude Code, OpenHands, LangChain, custom) into a unified trajectory protocol, run it against verifiable tasks (Jordan Count, OpenHands-bench, your own), observe via Langfuse, replay in a web UI, and — when the time comes — hook into RL frameworks like Agent Lightning without rewriting your agent code.

> **Status: Phase 1 in progress.** Protocol v0.1 formalized ([docs/TRAJECTORY_PROTOCOL.md](docs/TRAJECTORY_PROTOCOL.md)), 4 scaffold adapters (minimal, OpenAI Agents SDK, LangChain, Claude Code headless), schema validator + 11/11 conformance tests green. See [ROADMAP.md](ROADMAP.md).

## Why

Every agent scaffold (OpenAI Agents SDK, Claude Code, OpenHands, LangChain) has its own trajectory representation, its own tool-call encoding, its own trace format. That makes cross-scaffold evaluation, debugging, and RL integration a pile of ad-hoc adapters.

AgentAnvil's thesis: **one trajectory protocol, many adapters.** If the protocol is right, everything else — evaluation, visualization, RL wiring, sandbox isolation — composes cleanly on top.

## Architecture

```
           ┌─────────────────────────────────────────────────────┐
           │                    AgentAnvil                         │
           │                                                       │
 Task ───→ │   ┌──────────┐    ┌────────────┐    ┌─────────────┐  │
           │   │ Adapter  │───→│ Trajectory │───→│  Verifier   │  │
           │   │  Layer   │    │  Protocol  │    │  Registry   │  │
           │   └──────────┘    └──────┬─────┘    └─────────────┘  │
           │        │                 │                           │
           │    ┌───┴─────┐           ▼                           │
           │    │ scaffolds│    ┌────────────┐                    │
           │    │  • OpenAI│    │ Trace Sinks│                    │
           │    │    Agents│    │  • Local   │                    │
           │    │    SDK   │    │  • Langfuse│                    │
           │    │  • Minimal    └──────┬─────┘                    │
           │    │  • Claude Code       │                          │
           │    │  • OpenHands         ▼                          │
           │    │  • LangChain    ┌──────────┐                    │
           │    └─────────┘       │ Replay UI│ (Next.js)          │
           │                      └──────────┘                    │
           └─────────────────────────────────────────────────────┘
```

## Phase 0 Quickstart

```bash
# 1. Install
pip install -e .

# 2. Point at an LLM (Anthropic here; OpenAI variant in examples/)
export ANTHROPIC_API_KEY=...

# 3. Run one Jordan Count problem end-to-end
python examples/run_jordan_count.py --task-id task_000

# 4. View the trace
ls traces/traces.jsonl        # structured JSONL
cd ui && npm install && npm run dev
open http://localhost:3000
```

## Core Design

### 1. Unified Trajectory Protocol

A trajectory is a sequence of typed events. Every scaffold maps to the same types:

| Event         | Direction       | Meaning                          |
| ------------- | --------------- | -------------------------------- |
| `observation` | env → agent     | What the agent sees              |
| `thought`     | agent internal  | Reasoning / chain-of-thought     |
| `tool_call`   | agent → env     | Function / tool invocation       |
| `tool_result` | env → agent     | Result of the tool call          |
| `final_answer`| agent → env     | Terminal answer                  |
| `reward`      | verifier → log  | Scalar reward + correctness      |
| `error`       | any             | Failure state                    |

This is scaffold-agnostic, serializable to JSON, and deliberately narrow — the point is replay + scoring + RL reward assignment, not faithful reconstruction of scaffold internals.

### 2. Verifier Contract

```python
class Verifier(ABC):
    name: str
    def verify(self, final_answer: str, task) -> VerifyResult: ...
```

`VerifyResult` carries `correct`, `reward`, `parsed`, `gold`, `meta`. Strict parsing (no heuristic repair); unparseable answers count as wrong. See `agentanvil/verifier/jordan_count.py` for the reference implementation.

### 3. Trace Sinks

- **LocalJsonlSink** — append trajectories to `traces/traces.jsonl`. Always on. Required for the replay UI.
- **LangfuseSink** — emit trace + spans + scores. Requires `LANGFUSE_*` env vars.

## Scaffolds

| Scaffold            | Phase | Status    |
| ------------------- | ----- | --------- |
| Minimal (direct LLM)| 0     | ✅ skeleton |
| OpenAI Agents SDK   | 0     | ✅ skeleton |
| LangChain           | 1     | ✅ (tool loop via `intermediate_steps`) |
| Claude Code         | 1     | ✅ (headless CLI + `stream-json` parser; `from_stream()` for dep-free replay) |
| OpenHands           | 1     | planned   |
| Agent Lightning     | 2     | adapter stub for RL wiring |

## Verifiers

| Verifier      | Source                                         | Status    |
| ------------- | ---------------------------------------------- | --------- |
| Jordan Count  | [yaowubarbara/jordan-count](https://github.com/yaowubarbara/jordan-count) | ✅ skeleton |
| OpenHands-bench | TBD                                          | planned (P1) |
| SWE-bench-lite  | TBD                                          | planned (P1) |

## License

MIT.
