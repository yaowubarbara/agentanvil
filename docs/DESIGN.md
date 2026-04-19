# AgentAnvil — Design Summary

**One-sentence pitch**: a normalized trajectory protocol that lets any agent
scaffold's output feed one evaluator, one trace store, one replay UI, and
one RL training loop — without the scaffold knowing about any of them.

## The problem

Every agent scaffold — Claude Code, OpenAI Agents SDK, LangChain,
LangGraph, OpenHands, AutoGen, CrewAI, LlamaIndex — ships its own
trajectory representation. Tool calls are encoded differently. Tool
results are paired differently. Final answers live in different fields.
Cross-scaffold evaluation, debugging, and RL integration therefore
devolve into N × M adapter sprawl (N scaffolds, M downstream systems).

## The core bet

Fix the bet on the **trajectory shape** first. If the wire format is
right, each downstream concern (evaluator, trace sink, RL trainer,
sandbox runtime) plugs in as a thin layer.

## Protocol v0.1

A trajectory is a flat list of typed events (`observation`, `thought`,
`tool_call`, `tool_result`, `final_answer`, `reward`, `error`). Eight
MUST rules enforce shape: first event is an observation, last
non-reward event is terminal, step indices are contiguous, every
`tool_result` pairs with a preceding `tool_call`, etc. A stdlib-only
validator (`agentanvil.schema.validate`) enforces conformance at
runtime; every adapter ships a `from_*()` fixture helper so the
conformance test suite runs without any scaffold installed.

## Layering

- **Adapters** translate scaffold native output → v0.1 events.
- **Verifiers** take the trajectory's `final_answer` + task → binary
  reward with strict parsing.
- **Evaluators** (programmatic / rubric / LLM-as-judge) return richer
  named `EvalScore` objects orthogonal to reward.
- **Trace sinks** (Local JSONL / Langfuse / OpenTelemetry) consume
  finished trajectories.
- **Runtime isolation** layers: a narrow-scope Rust sidecar supervisor
  (PID + RSS + timeout + heartbeat, ~270 LOC), OpenSandbox for
  syscall-level isolation (gVisor / Kata / Firecracker), and a
  production-flavored K8s Helm chart.
- **RL integration**: `AnvilLitAgent` dynamically subclasses
  `agentlightning.LitAgent` when the package is importable, passes
  rollouts into the trainer; the whole harness is an Agent Lightning
  data source.

## What this is NOT

Not a scaffold. Not a replacement for Langfuse or LangSmith — those are
sinks AgentAnvil feeds. Not a sandbox — that's OpenSandbox's job. Not
an RL trainer — that's Agent Lightning's job. AgentAnvil is the thin
standardizing layer that makes those four services compose.

## Current scope

8 adapters · 4 verifiers · 7 evaluators · 5 dataset packs · 3 trace sinks
· Rust supervisor · Helm chart · Next.js dashboard · 96 tests green ·
~7k LOC · 11 commits.
