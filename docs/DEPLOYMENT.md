# Deployment Guide

AgentAnvil runs three ways:

1. **Local development** — Python harness + Next.js dev server + JSONL traces
2. **Single-host ops** — add the Rust supervisor for timeout / RSS monitoring
3. **Kubernetes** — Helm chart with production-flavored securityContext

## 1. Local dev

```bash
pip install -e '.[all]'
export ANTHROPIC_API_KEY=...

# Run one task
python examples/run_jordan_count.py --task-id task_000

# Run a whole pack via CLI
aa eval run gsm8k-mini --adapter minimal --model claude-sonnet-4-6 --limit 5

# Inspect results
aa traces tail
aa traces stats
aa validate traces/traces.jsonl

# Start the UI
cd ui && npm install && npm run dev   # -> http://localhost:3001
```

## 2. Single-host with Rust supervisor

The supervisor enforces wall-clock timeout + monitors peak RSS + accepts
JSON heartbeats from the Python rollout. It runs any child process; AgentAnvil
rollouts specifically connect to `$AGENTANVIL_SUPER_SOCK` via `SupervisorClient`.

```bash
# Build
cd supervisor && cargo build --release

# Run a timeout-supervised rollout
./target/release/agentanvil-supervisor run \
    --timeout 300 --grace 10 \
    --socket /tmp/anvil.sock \
    -- python3 ../examples/run_jordan_count.py
```

Exit code reflects the child's exit code, with `137` for SIGKILL (timeout +
grace exceeded) and `143` for SIGTERM (timeout, child honored the signal).
The final report appears on stderr:

```
ANVIL_REPORT: {"ok":true,"exit_code":0,"signaled":null,"duration_ms":803,
               "rss_peak_kb":13596,"termination_reason":{"kind":"completed"},
               "heartbeats":[...]}
```

### What the supervisor does NOT do

This is a supervisor, not a sandbox. It does NOT:
- apply seccomp-bpf syscall filters
- create Linux namespaces
- enforce cgroup resource limits (it observes RSS; it does not cap it)
- isolate the filesystem

Those concerns belong one level up — in the container runtime, or
OpenSandbox, or the K8s pod spec. See [Layer 3](#3-kubernetes) below.

## 3. Kubernetes

```bash
./deploy/kind-setup.sh
# creates kind cluster, builds UI image, helm installs agentanvil
```

The Helm chart (`deploy/helm/agentanvil/`) provisions:

| Resource | Purpose |
|---|---|
| `Deployment` | N replicas of the Next.js UI, stateless, read-only `/data/traces` |
| `Service` | ClusterIP on port 80 → container port 3001 |
| `ConfigMap` | `AGENTANVIL_TRACES` path + optional `LANGFUSE_HOST` |
| `PersistentVolumeClaim` | Shared traces directory (RWX, configurable RWO on single-node) |
| `Job` (template) | On-demand rollout job running the Rust supervisor + Python harness |

### Security posture (production defaults)

The chart sets six hardening flags by default. These are the bare minimum
for a serious production deployment; loosen only with explicit justification.

```yaml
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1001
  fsGroup: 1001
  seccompProfile:
    type: RuntimeDefault

containerSecurityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 1001
  capabilities:
    drop: [ALL]
```

Because Next.js requires a writable `.next/cache`, the chart mounts a
memory-backed `emptyDir` at `/app/.next/cache` and at `/tmp`. This preserves
`readOnlyRootFilesystem: true` without breaking Next.js.

### Customization knobs

See `deploy/helm/agentanvil/values.yaml`. Common overrides:

```bash
# smaller cluster — single-node access mode
helm upgrade agentanvil ./deploy/helm/agentanvil \
    --set traces.persistence.accessMode=ReadWriteOnce \
    --set replicaCount=1

# different registry / tag
helm upgrade agentanvil ./deploy/helm/agentanvil \
    --set image.repository=my-registry/agentanvil-ui \
    --set image.tag=2026-04-19

# wire Langfuse host
helm upgrade agentanvil ./deploy/helm/agentanvil \
    --set langfuse.hostUrl=http://langfuse.monitoring.svc:3000
```

### Observability

The UI serves `/api/traces` which is the liveness + readiness probe endpoint.
The `/api/traces` call reads the shared PVC; if the volume cannot be mounted,
the probe fails and the pod is recycled.

For more structured observability, enable the `OpenTelemetrySink` in your
rollout code — emits one span per trajectory event to any OTel-compatible
backend (Jaeger, Tempo, Honeycomb, Phoenix).

### Scaling considerations

- **UI pods** scale linearly; the PVC is read-only from their side.
- **Rollout jobs** are ephemeral and pull from a shared queue in production
  setups; the current chart launches one Job per `helm upgrade`.
- **Traces PVC** becomes a bottleneck at scale — plan to migrate to a
  database-backed trace sink (Postgres / Clickhouse) before > 1M trajectories.

## See also

- [ADAPTERS.md](ADAPTERS.md) — building new scaffold adapters
- [VERIFIERS.md](VERIFIERS.md) — verifier + evaluator design
- [TRAJECTORY_PROTOCOL.md](TRAJECTORY_PROTOCOL.md) — the wire contract
- `supervisor/README.md` — Rust supervisor scope statement
- `deploy/helm/agentanvil/values.yaml` — every tunable knob
