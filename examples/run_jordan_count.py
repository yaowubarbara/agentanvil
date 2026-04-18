"""
Phase 0 smoke test: run one Jordan Count task end-to-end.

  1. Load a sample task (run examples/generate_sample_task.py first).
  2. Run the minimal adapter (Anthropic or OpenAI).
  3. Verify with the strict ANSWER parser.
  4. Append to traces/traces.jsonl (and optionally Langfuse if envvars set).
  5. Print a summary so you can eyeball correctness before opening the UI.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from agentanvil import run_one
from agentanvil.adapter.minimal import MinimalAdapter
from agentanvil.trace.local import LocalJsonlSink
from agentanvil.verifier.jordan_count import JordanCountTask, JordanCountVerifier


def load_task(task_id: str) -> JordanCountTask:
    path = Path(__file__).parent / "sample_tasks" / f"{task_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python examples/generate_sample_task.py` first."
        )
    data = json.loads(path.read_text())
    return JordanCountTask(
        task_id=data["task_id"],
        image_path=data.get("image_path"),
        gold_count=data["gold_count"],
        dots=data.get("dots"),
        curve_points=data.get("curve_points"),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", default="task_000")
    ap.add_argument("--provider", default="anthropic", choices=["anthropic", "openai"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--langfuse", action="store_true", help="also write to Langfuse")
    ap.add_argument("--traces-path", default="traces/traces.jsonl")
    args = ap.parse_args()

    task = load_task(args.task_id)
    adapter = MinimalAdapter(provider=args.provider, model=args.model)
    verifier = JordanCountVerifier()

    sinks = [LocalJsonlSink(args.traces_path)]
    if args.langfuse:
        from agentanvil.trace.langfuse import LangfuseSink
        sinks.append(LangfuseSink())

    traj, result = run_one(adapter, task, verifier, sinks)

    print("─" * 60)
    print(f"task_id:      {task.task_id}")
    print(f"scaffold:     {traj.scaffold}")
    print(f"trajectory:   {traj.trajectory_id}")
    print(f"events:       {len(traj.events)}")
    print(f"final_answer: {traj.final_answer()!r}")
    print(f"parsed:       {result.parsed}")
    print(f"gold:         {result.gold}")
    print(f"correct:      {result.correct}")
    print(f"reward:       {result.reward}")
    print(f"direction:    {result.meta.get('direction')}")
    print(f"saved to:     {args.traces_path}")
    print("─" * 60)


if __name__ == "__main__":
    main()
