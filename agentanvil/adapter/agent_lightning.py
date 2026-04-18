"""
Agent Lightning integration surface — STUB.

Scope statement (important):
    This module demonstrates the *integration contract* between AgentAnvil and
    an RL trainer. It does NOT run training. The platform-engineer role this
    project targets is "build the harness so the algo team can plug in their
    trainer" — not "train the model ourselves". Every function here is either:
      (a) a conversion between AgentAnvil's Trajectory/VerifyResult and the
          rollout shape a trainer consumes, OR
      (b) a stand-in "trainer" that accepts rollouts and reports statistics,
          so the pipeline is testable end-to-end without installing the real
          agent-lightning package.

When the real agent-lightning library is installed, replace:
    ALRollout              -> agent_lightning.Rollout
    ALTrainerStub.consume  -> trainer.training_step
The conversion functions remain unchanged — that's the point of the surface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

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
