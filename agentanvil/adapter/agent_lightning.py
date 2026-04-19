"""
Agent Lightning integration (real + stub, auto-selected).

Agent Lightning (Microsoft Research, 2025) is the "PyTorch Lightning" of agent
RL — you subclass a LitAgent, implement a rollout method, and hand the class
to a Trainer that drives batches of tasks, collects (prompt, response, reward)
tuples, and runs policy optimization.

This module provides:

  1. Conversion functions                (trajectory → rollout shapes)
  2. AnvilLitAgent (stub-friendly)       — works without agent-lightning
  3. build_lit_agent()                   — returns a real LitAgent subclass
                                           when agent-lightning is importable,
                                           otherwise returns AnvilLitAgent
  4. train_with_agent_lightning()        — one-liner to actually run training
  5. ALTrainerStub                       — in-repo fake trainer for tests

So: if `pip install agent-lightning` is done, calling train_with_agent_lightning()
kicks off a real training loop with our AnvilAgents as policies. If it's not
installed, AnvilLitAgent + ALTrainerStub cover the full pipeline for tests and
for teams that aren't running RL yet.

Design note: the harness is not an RL trainer. We do NOT try to implement
policy gradient / PPO / etc. here. We implement the INTEGRATION CONTRACT —
the shape of data agent-lightning (or any similar trainer) consumes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from ..trajectory import EventKind, Trajectory
from ..verifier.base import VerifyResult


@dataclass
class ALRollout:
    """In-repo stand-in for agent_lightning.Rollout.

    Documents the fields we populate from an AgentAnvil trajectory. The real
    Agent Lightning class may have more fields — they default in its own
    constructor and AgentAnvil does not need to set them.
    """

    trajectory_id: str
    task_id: str
    scaffold: str
    prompt: str
    response: str
    reward: float
    meta: dict = field(default_factory=dict)


def trajectory_to_al_rollout(traj: Trajectory, verify: VerifyResult) -> ALRollout:
    """Flatten a trajectory to the canonical (prompt, response, reward) rollout.

    This is the shape most RL-from-outcome trainers consume. Rich-trajectory
    variants (credit assignment over tool loops) use the richer conversion
    below.
    """
    obs_events = [e for e in traj.events if e.kind == EventKind.OBSERVATION]
    prompt = ""
    if obs_events:
        c = obs_events[0].content
        prompt = c.get("text", str(c)) if isinstance(c, dict) else str(c)

    n_tool_calls = sum(1 for e in traj.events if e.kind == EventKind.TOOL_CALL)
    meta = {
        "correct": verify.correct,
        "parsed": verify.parsed,
        "gold": verify.gold,
        "n_events": len(traj.events),
        "n_tool_calls": n_tool_calls,
    }
    meta.update(verify.meta)
    return ALRollout(
        trajectory_id=traj.trajectory_id,
        task_id=traj.task_id,
        scaffold=traj.scaffold,
        prompt=prompt,
        response=traj.final_answer() or "",
        reward=float(verify.reward),
        meta=meta,
    )


def trajectory_to_al_steps(traj: Trajectory, verify: VerifyResult) -> list[dict]:
    """Step-level conversion for trainers that do credit assignment over tool loops.

    Each tool_call → tool_result pair becomes a step with the tool_call as action
    and the tool_result as next observation. Terminal reward is assigned to the
    final step only (pure RL-from-outcome, no dense reward shaping).

    STUB: the exact shape will be pinned to a specific Agent Lightning version
    during Phase 2+ integration. This sketch is already compatible with
    trainers that take `{"obs", "action", "reward", "done"}` tuples.
    """
    steps: list[dict] = []
    current: dict | None = None
    for e in traj.events:
        if e.kind == EventKind.OBSERVATION:
            if current is not None:
                steps.append(current)
            current = {"obs": e.content, "ts": e.ts, "action": None, "reward": 0.0, "done": False}
        elif e.kind == EventKind.TOOL_CALL and current is not None:
            current["action"] = e.content
        elif e.kind == EventKind.TOOL_RESULT and current is not None:
            steps.append(current)
            current = {"obs": e.content, "ts": e.ts, "action": None, "reward": 0.0, "done": False}
        elif e.kind == EventKind.FINAL_ANSWER and current is not None:
            current["action"] = {"final_answer": e.content}
            current["reward"] = float(verify.reward)
            current["done"] = True
            steps.append(current)
            current = None
    if current is not None:
        current["done"] = True
        steps.append(current)
    return steps


class ALTrainerStub:
    """Minimal stand-in for an Agent Lightning trainer.

    Accepts rollouts, aggregates statistics. Has no model, no optimizer — the
    real trainer replaces this class and keeps the `consume` contract.
    """

    def __init__(self) -> None:
        self.rollouts: list[ALRollout] = []

    def consume(self, rollout: ALRollout) -> None:
        self.rollouts.append(rollout)

    def consume_many(self, rollouts: Iterable[ALRollout]) -> None:
        for r in rollouts:
            self.consume(r)

    def report(self) -> dict:
        if not self.rollouts:
            return {"n": 0, "mean_reward": 0.0, "accuracy": 0.0, "scaffolds": []}
        rewards = [r.reward for r in self.rollouts]
        correct = sum(1 for r in self.rollouts if r.meta.get("correct"))
        return {
            "n": len(self.rollouts),
            "mean_reward": sum(rewards) / len(rewards),
            "accuracy": correct / len(self.rollouts),
            "scaffolds": sorted({r.scaffold for r in self.rollouts}),
            "per_scaffold": {
                sc: sum(1 for r in self.rollouts if r.scaffold == sc and r.meta.get("correct"))
                / max(1, sum(1 for r in self.rollouts if r.scaffold == sc))
                for sc in {r.scaffold for r in self.rollouts}
            },
        }


# ── Real Agent Lightning integration ────────────────────────────────

class AnvilLitAgent:
    """A LitAgent-shaped object bound to AgentAnvil components.

    When agent-lightning is NOT installed, this class can stand on its own —
    it still produces rollouts via its `rollout()` method and can be driven
    by ALTrainerStub. When agent-lightning IS installed, `build_lit_agent()`
    returns a subclass of `agentlightning.LitAgent` that delegates to this
    class, so the same rollout logic is used in both paths.

    Method contract (what a real Agent Lightning Trainer calls):
      - rollout(task) -> ALRollout        # per-task rollout
      - training_step(batch) -> list[ALRollout]  # batched rollout
      - validation_step(batch) -> list[ALRollout]
    """

    def __init__(
        self,
        anvil_agent,
        verifier,
        scaffold_hint: Optional[str] = None,
    ):
        self.anvil_agent = anvil_agent
        self.verifier = verifier
        self.scaffold_hint = scaffold_hint or getattr(anvil_agent, "scaffold_name", "unknown")
        self._rollout_count = 0

    def rollout(self, task) -> ALRollout:
        traj = self.anvil_agent.run(task)
        final = traj.final_answer() or ""
        vr = self.verifier.verify(final, task)
        vr.meta.setdefault("verifier", getattr(self.verifier, "name", "unknown"))
        self._rollout_count += 1
        # Emit a REWARD event on the trajectory so the trace carries the
        # reward signal too — matches what agentanvil.runner.run_one does.
        traj.emit(
            EventKind.REWARD,
            {
                "reward": vr.reward,
                "correct": vr.correct,
                "parsed": vr.parsed,
                "gold": vr.gold,
                "verifier": vr.meta.get("verifier"),
            },
        )
        rollout = trajectory_to_al_rollout(traj, vr)
        rollout.meta["trajectory"] = traj.to_json()  # attach full trace for trainers that want it
        rollout.meta["rollout_idx"] = self._rollout_count
        return rollout

    def training_step(self, batch: Sequence) -> list[ALRollout]:
        return [self.rollout(t) for t in batch]

    def validation_step(self, batch: Sequence) -> list[ALRollout]:
        return [self.rollout(t) for t in batch]


def build_lit_agent(anvil_agent, verifier, scaffold_hint: Optional[str] = None):
    """Build an Agent Lightning `LitAgent` subclass bound to AgentAnvil.

    If agent-lightning is installed, returns a real `agentlightning.LitAgent`
    subclass that delegates to AnvilLitAgent. If not, returns AnvilLitAgent
    directly — same interface, same behavior, just not a subclass of the
    real base.
    """
    inner = AnvilLitAgent(anvil_agent, verifier, scaffold_hint=scaffold_hint)
    try:
        from agentlightning import LitAgent  # type: ignore
    except ImportError:
        return inner

    class _AnvilBackedLitAgent(LitAgent):   # type: ignore[misc]
        def __init__(self):
            super().__init__()
            self._inner = inner

        def rollout(self, task):
            return self._inner.rollout(task)

        def training_step(self, batch, batch_idx=None):
            return self._inner.training_step(batch)

        def validation_step(self, batch, batch_idx=None):
            return self._inner.validation_step(batch)

    return _AnvilBackedLitAgent()


def train_with_agent_lightning(
    anvil_agent,
    verifier,
    dataset,
    max_epochs: int = 1,
    batch_size: int = 4,
    trainer_kwargs: Optional[dict] = None,
    fallback_to_stub: bool = True,
):
    """Run a real Agent Lightning training loop over an AgentAnvil dataset.

    If agent-lightning is installed, uses their Trainer + TaskLoader. If not
    and `fallback_to_stub=True`, runs through ALTrainerStub so the pipeline
    still exercises end-to-end; returns the stub trainer with aggregated stats.

    Returns: the (real or stub) trainer, the lit_agent, and (for real runs)
    any fit metrics agent-lightning surfaces.
    """
    lit_agent = build_lit_agent(anvil_agent, verifier)

    try:
        from agentlightning import Trainer as ALTrainer  # type: ignore
        from agentlightning import TaskLoader  # type: ignore
    except ImportError:
        if not fallback_to_stub:
            raise ImportError(
                "pip install agent-lightning, or pass fallback_to_stub=True"
            )
        stub = ALTrainerStub()
        tasks = list(dataset.tasks) if hasattr(dataset, "tasks") else list(dataset)
        for epoch in range(max_epochs):
            for i in range(0, len(tasks), batch_size):
                batch = tasks[i : i + batch_size]
                for r in lit_agent.training_step(batch):
                    stub.consume(r)
        return {"trainer": stub, "lit_agent": lit_agent, "report": stub.report(), "path": "stub"}

    kwargs = dict(trainer_kwargs or {})
    kwargs.setdefault("max_epochs", max_epochs)
    trainer = ALTrainer(**kwargs)
    tasks = list(dataset.tasks) if hasattr(dataset, "tasks") else list(dataset)
    loader = TaskLoader(tasks, batch_size=batch_size)
    trainer.fit(lit_agent, loader)
    return {"trainer": trainer, "lit_agent": lit_agent, "report": None, "path": "real"}
