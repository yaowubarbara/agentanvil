# agentanvil-supervisor

Narrow-scope process supervisor for AgentAnvil rollouts. Written in Rust for
systems-level correctness on signal handling and timing; kept deliberately
small so the blast radius of a bug is contained.

## What this supervisor does (exactly three things)

1. **Monitor child PID + peak RSS.** Polls `/proc/<pid>/status` every
   `--poll-ms` milliseconds while the child is alive, tracking peak
   `VmRSS`. Linux-only.

2. **Enforce wall-clock timeout with SIGTERM → SIGKILL escalation.**
   When `--timeout` elapses, send `SIGTERM`. If the child has not exited
   after `--grace` more seconds, send `SIGKILL`. Record which escalation
   step was used.

3. **Accept Python-side heartbeats over a Unix domain socket.** Child
   reads `AGENTANVIL_SUPER_SOCK` from env and may (optionally) connect
   and stream JSON heartbeats (`start`, `progress`, `finish`). Supervisor
   buffers them and includes the full list in its final report.

## What this supervisor does NOT do (on purpose)

This is a supervisor, not a jail. The following are deliberately out of
scope and are the responsibility of OpenSandbox, Firecracker, gVisor, or
the Kubernetes runtime, as appropriate:

- seccomp-bpf syscall filtering
- Linux namespace isolation (user/pid/mount/net)
- cgroup resource enforcement (we *observe* RSS; we do not *cap* it)
- filesystem layering or read-only roots
- capability dropping beyond what the parent process already imposes
- network egress policy

Those belong in the Helm chart's `securityContext`, the OpenSandbox
container runtime, or the pod-level NetworkPolicy. Keeping this crate
narrow lets those concerns evolve independently.

## Usage

```
agentanvil-supervisor run \
    --timeout 300 --grace 10 \
    --socket /tmp/anvil.sock \
    --poll-ms 200 \
    -- python examples/run_jordan_count.py --task-id task_000
```

The supervisor exits with the child's exit code (or `137` if SIGKILL was
sent, `143` if only SIGTERM). A JSON report is written to stderr on the
line starting with `ANVIL_REPORT:`:

```
ANVIL_REPORT: {"ok":true,"exit_code":0,"duration_ms":4237,"rss_peak_kb":45632,"termination_reason":"Completed","heartbeats":[...]}
```

## Python heartbeat client

Minimal Python client in `agentanvil/supervisor_client.py` sends heartbeats
if `AGENTANVIL_SUPER_SOCK` is set; silently no-ops otherwise, so the same
Python script runs with or without supervision.
