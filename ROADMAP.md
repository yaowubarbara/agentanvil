# AgentAnvil Roadmap

## Phase 0 — Walking skeleton (current)

**Goal**: prove the trajectory protocol + one end-to-end run (minimal adapter → Jordan Count → local trace → UI replay).

- [x] Repo layout
- [x] Unified trajectory protocol (`agentanvil/trajectory.py`)
- [x] AnvilAgent base (`agentanvil/agent.py`)
- [x] Verifier base (`agentanvil/verifier/base.py`)
- [x] Jordan Count verifier (strict ANSWER parser + crossing-number gold)
- [x] Minimal adapter (direct Anthropic / OpenAI call)
- [x] OpenAI Agents SDK adapter (skeleton; refined in P1)
- [x] Local JSONL sink
- [x] Langfuse sink skeleton
- [x] Docker Compose for Langfuse self-host
- [x] Next.js replay UI (minimal)
- [x] `examples/run_jordan_count.py` smoke test

## Phase 1 — Scaffold breadth + protocol v0.1

**Goal**: prove the protocol survives contact with 3+ scaffolds, publish a versioned spec.

- [x] `docs/TRAJECTORY_PROTOCOL.md` — v0.1 spec (event schema, tool-call normalization, MUST rules)
- [x] `agentanvil/schema.py` — runtime validator for the MUST rules
- [x] LangChain adapter (tool loop via `intermediate_steps`)
- [x] Claude Code adapter (headless CLI + `stream-json` stream parser + `from_stream()` replay)
- [x] 11/11 conformance tests (4 scaffolds positive + 7 negative + Claude Code stream-mapping spot check)
- [x] Diff UI: side-by-side step-aligned replay with divergence highlighting; sidebar pick-A/pick-B selector
- [x] `examples/seed_demo_traces.py`: dependency-free demo fixture (claude-code correct vs minimal overcount on the same task_id)
- [ ] OpenHands adapter
- [ ] Claude Agent SDK variant (second Claude Code integration path)
- [ ] OpenHands-bench verifier (subset)
- [ ] Langfuse sink hardened (prompt cache, latency, token accounting)

## Phase 2 — Ops + systems signal

**Goal**: prove the harness is deployable, isolated, and RL-frameworks-ready.

- [x] **Rust sidecar supervisor** (narrow scope, enforced)
  - [x] Monitors Python runtime subprocess (PID + peak RSS)
  - [x] Enforces wall-clock timeout (SIGTERM → SIGKILL escalation)
  - [x] Reports status to Python runtime over Unix socket
  - [x] 2/2 unit tests + 3/3 integration smokes (normal / SIGTERM / SIGKILL)
  - [x] Python heartbeat client (no-op when AGENTANVIL_SUPER_SOCK unset)
  - **Explicitly NOT in scope**: seccomp profiles, syscall audit, namespace isolation, cgroup policy — these belong to OpenSandbox / gVisor / Firecracker and are out of scope for this supervisor
- [x] Agent Lightning adapter — **REAL, NOT STUB** (`agentanvil/adapter/agent_lightning.py`)
  - [x] `trajectory_to_al_rollout()` flat conversion for outcome-only trainers
  - [x] `trajectory_to_al_steps()` richer per-step conversion for credit assignment
  - [x] `AnvilLitAgent` implements the full `LitAgent` method contract
  - [x] `build_lit_agent()` returns real `agentlightning.LitAgent` subclass when installed
  - [x] `train_with_agent_lightning()` one-liner — calls real Trainer.fit() OR falls back to ALTrainerStub
  - [x] 5/5 stub + 7/7 real-integration tests green
- [x] Helm chart for K8s (`deploy/helm/agentanvil/`)
  - [x] Deployment + Service + ConfigMap + PVC + example rollout Job
  - [x] Production-flavored defaults: runAsNonRoot, readOnlyRootFilesystem, drop ALL caps, seccompProfile=RuntimeDefault
  - [x] Liveness + readiness probes on `/api/traces`
  - [x] Multi-stage Dockerfile for the UI (non-root, tmpfs for Next.js cache)
  - [x] `deploy/kind-setup.sh` one-command local cluster
  - [x] `helm lint` clean + `helm template` renders
- [x] **OpenSandbox runtime integration** (`agentanvil/runtime/opensandbox.py`)
  - [x] `OpenSandboxRuntime` wrapper with gVisor/Kata/Firecracker runtime selection
  - [x] Stateful code-interpreter context (pip installs persist across `code.run()`)
  - [x] `ToolCallRouter` maps `python.exec` / `shell.run` / `fs.read` / `fs.write` to execd endpoints
  - [x] Lazy import of `opensandbox` PyPI SDK + `StubClient` for dependency-free testing
  - [x] 14/14 tests green (lifecycle + code context + command + file I/O + router)
- [ ] Multi-replica stress demo (real cluster)

## Phase 3 — Differentiated contribution (optional)

- [ ] Trajectory protocol RFC-style public spec
- [ ] Cross-scaffold leaderboard on Jordan Count (Sonnet / GPT-5 / Gemini / open models)
- [ ] arXiv short paper: "Scaffold-Agnostic Agent Evaluation: A Protocol Proposal"
