"""
Real Agent Lightning rollout — end-to-end demonstration.

This script drives the complete RL-training loop: AgentAnvil scaffold
produces trajectories, the verifier scores them, AnvilLitAgent wraps the
whole thing as an Agent Lightning LitAgent, and we call Trainer.fit()
with real data.

Three execution modes, auto-selected:

  1. FULL PATH (agent-lightning installed + ANTHROPIC_API_KEY set):
     - pip install agent-lightning
     - export ANTHROPIC_API_KEY=sk-ant-...
     - real Anthropic calls, real LitAgent.training_step, real rollouts
     through agent_lightning.Trainer.

  2. STUB-TRAINER PATH (no agent-lightning, API key set):
     - MinimalAdapter hits the real Claude API
     - ALTrainerStub collects the rollouts
     - proves everything from rollout → reward → aggregator works live,
       minus the actual policy update step.

  3. FULLY OFFLINE PATH (no agent-lightning, no API key):
     - a recorded-fixture stub agent produces trajectories
     - ALTrainerStub aggregates them
     - proves pipeline shape without any external dependency.

Intended use:

  python3 examples/real_rl_rollout.py --pack gsm8k-mini --limit 5

  (optional) --mode {auto,full,stub,offline}  — force a specific path
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentanvil import AnvilAgent, AnvilTask
from agentanvil.adapter.agent_lightning import (
    ALTrainerStub,
    AnvilLitAgent,
    build_lit_agent,
    train_with_agent_lightning,
)
from agentanvil.adapter.minimal import MinimalAdapter
from agentanvil.dataset import Dataset
from agentanvil.trajectory import EventKind, Trajectory
from agentanvil.verifier.base import VerifyResult, Verifier


class _OfflineStubAgent(AnvilAgent):
    """For the fully-offline mode. Produces deterministic trajectories
    mimicking a vaguely-competent agent: gets ~60% right by echoing the
    first integer in the gold answer when the task exposes one."""

    scaffold_name = "offline-stub"

    def run(self, task: AnvilTask) -> Trajectory:
        import re
        t = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        obs = task.initial_observation()
        t.emit(EventKind.OBSERVATION, obs)
        t.emit(EventKind.THOUGHT, {"text": "offline stub: reasoning..."})
        # try to echo gold answer's last integer; otherwise guess 42
        gold_src = getattr(task, "gold_answer", None) or getattr(task, "gold_count", None) or ""
        m = re.findall(r"-?\d+", str(gold_src))
        # 60% of the time return gold; 40% return wrong
        import hashlib
        h = int(hashlib.md5(task.task_id.encode()).hexdigest(), 16)
        if h % 5 < 3 and m:
            answer = f"#### {m[-1]}"
        else:
            answer = "#### 42"
        t.emit(EventKind.FINAL_ANSWER, answer, model="offline-stub")
        t.finish()
        return t


def detect_mode(forced: str) -> str:
    if forced != "auto":
        return forced
    try:
        import agentlightning  # noqa: F401
        has_lib = True
    except ImportError:
        has_lib = False
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if has_lib and has_key:
        return "full"
    if has_key:
        return "stub"
    return "offline"


def run_full_mode(dataset: Dataset, limit: int, verbose: bool) -> dict:
    """Real agent-lightning Trainer.fit() with real Anthropic-backed rollouts."""
    print("MODE: full — agent-lightning + Anthropic API, real training loop")
    agent = MinimalAdapter(provider="anthropic", model="claude-sonnet-4-6")
    verifier = dataset.verifier()
    subset = dataset.take(limit) if limit else dataset

    result = train_with_agent_lightning(
        anvil_agent=agent,
        verifier=verifier,
        dataset=subset,
        max_epochs=1,
        batch_size=2,
        fallback_to_stub=False,   # force real path
    )
    print(f"trainer type: {type(result['trainer']).__name__}")
    print(f"lit_agent type: {type(result['lit_agent']).__name__}")
    print(f"training path: {result['path']}")
    return result


def run_stub_trainer_mode(dataset: Dataset, limit: int, verbose: bool) -> dict:
    """Real Anthropic rollouts, stub trainer. Proves rollout → reward shape
    works end-to-end with live API but no RL library installed yet."""
    print("MODE: stub-trainer — real Anthropic calls, ALTrainerStub aggregates")
    agent = MinimalAdapter(provider="anthropic", model="claude-sonnet-4-6")
    verifier = dataset.verifier()
    subset = dataset.take(limit) if limit else dataset

    lit = AnvilLitAgent(agent, verifier)
    trainer = ALTrainerStub()

    tasks = subset.tasks
    for i in range(0, len(tasks), 2):
        batch = tasks[i : i + 2]
        rollouts = lit.training_step(batch)
        for r in rollouts:
            trainer.consume(r)
            if verbose:
                print(f"  {r.task_id:<24} scaffold={r.scaffold} reward={r.reward} "
                      f"parsed={r.meta.get('parsed')} gold={r.meta.get('gold')}")

    report = trainer.report()
    return {"trainer": trainer, "lit_agent": lit, "report": report, "path": "stub-real-api"}


def run_offline_mode(dataset: Dataset, limit: int, verbose: bool) -> dict:
    """No external deps. Proves the full harness without internet."""
    print("MODE: offline — deterministic stub agent, stub trainer, no API calls")
    agent = _OfflineStubAgent()
    verifier = dataset.verifier()
    subset = dataset.take(limit) if limit else dataset

    lit = AnvilLitAgent(agent, verifier)
    trainer = ALTrainerStub()
    for t in subset.tasks:
        r = lit.rollout(t)
        trainer.consume(r)
        if verbose:
            print(f"  {r.task_id:<24} scaffold={r.scaffold} reward={r.reward}")

    report = trainer.report()
    return {"trainer": trainer, "lit_agent": lit, "report": report, "path": "offline-stub"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pack", default="gsm8k-mini", help="task pack name under agentanvil/packs/")
    ap.add_argument("--limit", type=int, default=5, help="max tasks to run from the pack")
    ap.add_argument("--mode", choices=["auto", "full", "stub", "offline"], default="auto",
                    help="auto = best available; full requires agent-lightning + ANTHROPIC_API_KEY")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    dataset = Dataset.from_pack(args.pack)
    print("─" * 60)
    print(f"Pack:     {args.pack} ({len(dataset)} tasks total)")
    print(f"Limit:    {args.limit}")
    print(f"Verifier: {dataset.meta.verifier}")

    mode = detect_mode(args.mode)
    print(f"Mode:     {mode}")
    print("─" * 60)

    if mode == "full":
        result = run_full_mode(dataset, args.limit, args.verbose)
    elif mode == "stub":
        result = run_stub_trainer_mode(dataset, args.limit, args.verbose)
    else:
        result = run_offline_mode(dataset, args.limit, args.verbose)

    print("─" * 60)
    if result.get("report"):
        rep = result["report"]
        print(f"  n:          {rep['n']}")
        print(f"  accuracy:   {rep['accuracy']:.1%}")
        print(f"  mean_rwd:   {rep['mean_reward']:.3f}")
        print(f"  scaffolds:  {rep['scaffolds']}")
        if rep.get("per_scaffold"):
            for k, v in rep["per_scaffold"].items():
                print(f"     {k:<22} {v:.1%}")
    print(f"  path:       {result['path']}")
    print("─" * 60)


if __name__ == "__main__":
    main()
