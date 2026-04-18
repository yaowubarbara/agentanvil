"""
Minimal end-to-end demo of the supervisor ↔ Python heartbeat loop.

Run:
    ./supervisor/target/release/agentanvil-supervisor run \\
        --timeout 10 --grace 2 \\
        --socket /tmp/anvil-demo.sock \\
        -- python3 examples/supervise_demo.py

Expected: supervisor's ANVIL_REPORT on stderr lists 5 heartbeats
(start + 3 progress + finish) and reports ok=true.

Run without the supervisor, just `python3 examples/supervise_demo.py`,
and the script still completes — the client detects the absence of
AGENTANVIL_SUPER_SOCK and becomes a no-op.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentanvil.supervisor_client import SupervisorClient


def main():
    with SupervisorClient() as client:
        active = client.active
        client.start(trajectory_id="demo-run-001")
        print(f"[demo] supervised={active}, starting work")
        for step in range(3):
            time.sleep(0.2)
            client.progress(step=step, note=f"simulated step {step}")
            print(f"[demo] step {step} done")
        client.finish(ok=True, final_answer="ANSWER: 42")
        print("[demo] finished")


if __name__ == "__main__":
    main()
