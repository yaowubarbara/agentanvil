# AgentAnvil K8s Runbook

Operational reference for running AgentAnvil under Kubernetes. Written
during the first real kind-cluster smoke; updated as new failure modes
surface in production.

## TL;DR

```bash
./scripts/kind_deploy.sh     # one-command smoke: cluster → build → helm → verify
```

Artifacts from the most recent real run land in `docs/k8s-evidence/`:
`cluster-info.txt`, `get-all.txt`, `pod-describe.txt`, `pod-logs.txt`,
`events.txt`, `rollout-job-log.txt`, `ui-response-head.html`.

## Architecture (what actually runs in the cluster)

```
 Namespace: agentanvil
 ┌──────────────────────────────────────────────────┐
 │ Deployment  agentanvil          (2 replicas)     │
 │  └── Pod   ui container         port 3001        │
 │            uid 1001, readOnlyRootFilesystem      │
 │            mounts:                               │
 │              /data/traces     (RO, from PVC)     │
 │              /app/.next/cache (RW, emptyDir RAM) │
 │              /tmp             (RW, emptyDir)     │
 │                                                  │
 │ Service     agentanvil          ClusterIP :80    │
 │               └→ targetPort 3001                 │
 │                                                  │
 │ PVC         agentanvil-traces   ReadWriteMany    │
 │               (or RWO on single-node)            │
 │                                                  │
 │ ConfigMap   agentanvil-config                    │
 │   AGENTANVIL_TRACES=/data/traces/traces.jsonl    │
 │   NEXT_TELEMETRY_DISABLED=1                      │
 │                                                  │
 │ Job         agentanvil-rollout-<timestamp>       │
 │   (on-demand, see rolloutJob.enabled)            │
 │   runs Rust supervisor around Python harness     │
 │   writes trajectories back to the traces PVC     │
 └──────────────────────────────────────────────────┘
```

## SecurityContext — the six hardening flags

All six are set by default in `deploy/helm/agentanvil/values.yaml`. If you
loosen any of them in production, document why in that file's comments,
not in a patch or overlay.

| Flag | Value | Reason |
| --- | --- | --- |
| `runAsNonRoot` | `true` | defense-in-depth against container escape |
| `runAsUser` | `1001` | matches the `nextjs` user baked into the Dockerfile |
| `readOnlyRootFilesystem` | `true` | blocks live-patching the image |
| `allowPrivilegeEscalation` | `false` | no suid paths reachable |
| `capabilities.drop` | `[ALL]` | strictly only what Linux requires for exec |
| `seccompProfile.type` | `RuntimeDefault` | kernel-level syscall filter |

CI verifies these survive `helm template` via grep in
`.github/workflows/ci.yml` — the rendered YAML is asserted to still
contain each flag.

## Common operations

### Deploy from scratch
```bash
./scripts/kind_deploy.sh
```

### Just update the chart on an existing cluster
```bash
helm upgrade agentanvil deploy/helm/agentanvil \
    --namespace agentanvil --reuse-values
```

### Access the UI on localhost
```bash
kubectl --namespace agentanvil port-forward svc/agentanvil 3001:80
# open http://localhost:3001
```

### Watch a rolling restart live
```bash
kubectl --namespace agentanvil get pods -w
```

### Drop a new task pack into the shared PVC (dev only)
```bash
POD=$(kubectl --namespace agentanvil get pod -l app.kubernetes.io/name=agentanvil -o jsonpath='{.items[0].metadata.name}')
# Note: UI mounts traces RO; use a writer pod for this
kubectl --namespace agentanvil debug "$POD" --image=busybox --target=ui -- \
    /bin/sh -c "echo '<json>' >> /data/traces/traces.jsonl"
```

### Launch a rollout Job on demand
```bash
helm upgrade agentanvil deploy/helm/agentanvil \
    --namespace agentanvil --reuse-values \
    --set rolloutJob.enabled=true \
    --set 'rolloutJob.command=python3 /app/examples/run_jordan_count.py --task-id task_000'
```

### Tail UI pod logs
```bash
kubectl --namespace agentanvil logs -l app.kubernetes.io/name=agentanvil -f
```

## Failure modes & fixes

### Pod stuck `CrashLoopBackOff`
Most likely: `readOnlyRootFilesystem: true` is blocking Next.js from
writing to `.next/cache`. The chart mounts an `emptyDir` at that path,
but if someone forked the chart and removed the volume, Next.js crashes
silently — only the `/tmp` write usually survives.

**Debug**:
```bash
kubectl --namespace agentanvil describe pod <pod> | grep -A 10 "Last State"
kubectl --namespace agentanvil logs <pod> --previous
```

**Fix**: re-add the `next-cache` volume + volumeMount (see
`deploy/helm/agentanvil/templates/deployment.yaml` around the
`.Values.tmpfs.nextCache` block).

### Pod stuck `Pending`
Most likely: PVC can't bind because the storage class doesn't support
`ReadWriteMany` on a single-node cluster. kind-based demo runs must use
`accessMode: ReadWriteOnce` and `replicaCount: 1`.

**Debug**:
```bash
kubectl --namespace agentanvil describe pvc agentanvil-traces
kubectl --namespace agentanvil get events --sort-by='.lastTimestamp' | tail -20
```

**Fix**:
```bash
helm upgrade agentanvil deploy/helm/agentanvil \
    --namespace agentanvil --reuse-values \
    --set traces.persistence.accessMode=ReadWriteOnce \
    --set replicaCount=1
```

### Service returns 404 on `/api/traces`
UI container is healthy but the traces file isn't where it expects.
The `ConfigMap` sets `AGENTANVIL_TRACES`; the Deployment mounts the PVC at
the matching path. If the two diverge (someone changed one without the
other), the API route opens a nonexistent file and returns the empty-trajectories
response.

**Debug**:
```bash
kubectl --namespace agentanvil get cm agentanvil-config -o yaml
kubectl --namespace agentanvil exec -it deploy/agentanvil -- \
    ls -la /data/traces/
```

**Fix**: ensure `traces.mountPath` in values.yaml matches the directory
half of `AGENTANVIL_TRACES` in the ConfigMap. They both default to
`/data/traces`.

### Liveness probe flaps
If probes on `/api/traces` intermittently fail, Next.js cold-start may
exceed `initialDelaySeconds: 15`. Bump it:

```bash
helm upgrade agentanvil deploy/helm/agentanvil \
    --namespace agentanvil --reuse-values \
    --set livenessProbe.initialDelaySeconds=30 \
    --set livenessProbe.failureThreshold=5
```

## Scaling notes

- **UI pods** scale horizontally without coordination — they only read
  from the shared traces PVC.
- **Rollout Jobs** are idempotent per-invocation; if you want recurring
  eval runs, wrap them in a `CronJob` pointed at the same image.
- **Traces PVC** becomes a bottleneck past roughly 1 M trajectories on a
  single-node cluster. At that scale, migrate the trace sink from JSONL
  to a Postgres-backed sink (tracked in ROADMAP as Phase 2+/B4).

## Tear-down

```bash
kind delete cluster --name agentanvil-smoke
```

Removes every artifact — no residue on the host beyond Docker layers.

## What's intentionally NOT in this runbook

- **seccomp filter customization** — belongs in the OpenSandbox layer,
  not the UI pod
- **network policy / service mesh** — cluster-wide concern; bring your
  own (Cilium / Istio / NetworkPolicy resources outside this chart)
- **horizontal pod autoscaler / pod disruption budget** — intentional
  Phase 3 follow-up; small deployments don't need them and having them
  in the default chart makes new users burn time on quotas they haven't
  thought about yet

See the **ROADMAP.md** Phase 2+ section for what's queued next.
