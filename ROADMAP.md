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

- [ ] Claude Code adapter (headless subprocess / SDK)
- [ ] OpenHands adapter
- [ ] LangChain adapter
- [ ] `docs/TRAJECTORY_PROTOCOL.md` — v0.1 spec (event schema, JSON schema, tool-call normalization)
- [ ] Diff UI: run two scaffolds on the same task, side-by-side replay
- [ ] OpenHands-bench verifier (subset)
- [ ] Langfuse sink hardened (prompt cache, latency, token accounting)

## Phase 2 — Ops + systems signal

**Goal**: prove the harness is deployable, isolated, and RL-frameworks-ready.

- [ ] Helm chart for K8s (kind / k3d tested)
- [ ] **Rust sandbox supervisor** (narrow scope, deliberately)
  - Monitors Python runtime subprocess (PID, cpu, rss)
  - Enforces wall-clock timeout (SIGTERM → SIGKILL escalation)
  - Reports status to Python runtime over Unix socket
  - **Explicitly NOT in scope**: seccomp profiles, syscall audit, namespace isolation, cgroup policy — these belong to OpenSandbox / gVisor / Firecracker and are out of scope for this supervisor
- [ ] OpenSandbox integration as a runtime backend option
- [ ] Agent Lightning adapter stub — show the hook surface; do not train
- [ ] Multi-replica stress demo

## Phase 3 — Differentiated contribution (optional)

- [ ] Trajectory protocol RFC-style public spec
- [ ] Cross-scaffold leaderboard on Jordan Count (Sonnet / GPT-5 / Gemini / open models)
- [ ] arXiv short paper: "Scaffold-Agnostic Agent Evaluation: A Protocol Proposal"
