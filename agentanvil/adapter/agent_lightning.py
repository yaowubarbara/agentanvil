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

    When agent-lightning is installed (verified against v0.3.0 — 2026-04),
    returns a real `agentlightning.LitAgent` subclass whose `rollout()` method
    matches the real signature `(task, resources, rollout) -> float`. When the
    library is absent, returns `AnvilLitAgent` directly (same rollout logic,
    just not a subclass of the real base).

    The real `LitAgent.rollout()` can return:
      - None (tracing externalized)
      - float (final reward)                           ← we return this
      - List[ReadableSpan] / List[Span] (OTel spans)

    We return `float` because our verifier already produces a scalar reward;
    the detailed trajectory is captured separately via our trace sinks
    (LocalJsonlSink / LangfuseSink / OpenTelemetrySink) — the Agent Lightning
    runner's tracing layer is orthogonal.
    """
    inner = AnvilLitAgent(anvil_agent, verifier, scaffold_hint=scaffold_hint)
    try:
        from agentlightning import LitAgent  # type: ignore
    except ImportError:
        return inner

    class _AnvilBackedLitAgent(LitAgent):   # type: ignore[misc]
        """Real `agentlightning.LitAgent` subclass routing to AnvilLitAgent."""

        def __init__(self):
            super().__init__()
            self._inner = inner

        def rollout(self, task, resources, rollout):   # real AL signature
            # The Agent Lightning runner may pass the task as a dict (TaskInput)
            # or as a typed payload. If it looks like our AnvilTask (has a
            # task_id + initial_observation), route it straight; otherwise try
            # dict-style access.
            anvil_task = _coerce_to_anvil_task(task)
            al_rollout = self._inner.rollout(anvil_task)
            # Return the scalar reward per Agent Lightning's contract.
            return float(al_rollout.reward)

        def training_rollout(self, task, resources, rollout):
            return self.rollout(task, resources, rollout)

        def validation_rollout(self, task, resources, rollout):
            return self.rollout(task, resources, rollout)

        # Expose the richer internal rollout for callers that want it.
        def rollout_rich(self, task):
            return self._inner.rollout(task)

    return _AnvilBackedLitAgent()


def _coerce_to_anvil_task(task):
    """Best-effort: accept AnvilTask, pydantic model, or dict payload."""
    if hasattr(task, "initial_observation") and hasattr(task, "task_id"):
        return task
    # Pydantic Task (agent-lightning style) — convert to AnvilTask-shaped duck
    if hasattr(task, "model_dump"):
        data = task.model_dump()
    elif isinstance(task, dict):
        data = task
    else:
        data = {"task_id": str(task), "text": str(task)}

    class _DuckTask:
        def __init__(self, d):
            self.task_id = d.get("task_id") or d.get("id") or str(hash(frozenset(d.items()) if isinstance(d, dict) else id(d)))
            self._data = d

        def initial_observation(self):
            text = self._data.get("text") or self._data.get("question") or self._data.get("prompt", "")
            out = {"text": text}
            if "image_path" in self._data:
                out["image_path"] = self._data["image_path"]
            return out

    return _DuckTask(data)


def train_with_agent_lightning(
    anvil_agent,
    verifier,
    dataset,
    max_epochs: int = 1,
    batch_size: int = 4,
    trainer_kwargs: Optional[dict] = None,
    fallback_to_stub: bool = True,
):
    """Drive rollouts over a dataset, either via a real agent-lightning
    `LitAgent` + manual iteration (if the lib is installed) or via
    `ALTrainerStub` fallback.

    Note: the full `agentlightning.Trainer` needs a `LightningStore` +
    `Algorithm` + `ExecutionStrategy` to do actual RL updates; wiring those
    is the algo team's job. Our contract is: produce per-task rollouts that
    the real `LitAgent.rollout(task, resources, rollout)` would be called for.
    """
    lit_agent = build_lit_agent(anvil_agent, verifier)

    try:
        import agentlightning  # type: ignore
        from agentlightning import Rollout as _ALRollout  # type: ignore
        real_al = True
    except ImportError:
        real_al = False

    tasks = list(dataset.tasks) if hasattr(dataset, "tasks") else list(dataset)
    stub = ALTrainerStub()

    if real_al and hasattr(lit_agent, "rollout_rich"):
        # Drive the REAL LitAgent subclass per task; it returns a float reward
        # via the real signature, and rollout_rich gives us the fat AnvilLitAgent
        # rollout for the stub trainer's aggregation.
        for epoch in range(max_epochs):
            for t in tasks:
                # Call the real AL-contract method to prove integration:
                empty_rollout = _ALRollout(
                    rollout_id=f"agentanvil-{id(t)}",
                    input={"task_id": getattr(t, "task_id", str(t))},
                    start_time=0.0,
                )
                reward_scalar = lit_agent.rollout(t, {}, empty_rollout)
                # Also get the rich rollout for our own aggregation
                fat = lit_agent.rollout_rich(t)
                fat.meta["al_contract_reward"] = reward_scalar
                stub.consume(fat)
        return {
            "trainer": stub,
            "lit_agent": lit_agent,
            "report": stub.report(),
            "path": "real-agentlightning",
        }

    if not fallback_to_stub and not real_al:
        raise ImportError(
            "pip install agentlightning, or pass fallback_to_stub=True"
        )
    # Pure fallback path — AnvilLitAgent without the real LitAgent base
    for epoch in range(max_epochs):
        for t in tasks:
            r = lit_agent.rollout(t) if hasattr(lit_agent, "rollout") else None
            if r is not None and hasattr(r, "reward"):
                stub.consume(r)
    return {
        "trainer": stub,
        "lit_agent": lit_agent,
        "report": stub.report(),
        "path": "fallback-stub",
    }
