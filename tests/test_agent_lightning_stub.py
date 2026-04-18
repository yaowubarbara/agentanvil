"""
Tests for the Agent Lightning integration surface (stub).

Verifies:
  - Trajectory → ALRollout conversion preserves reward, correctness flags,
    and scaffold identity
  - Step-level conversion places terminal reward on the final step only
  - ALTrainerStub aggregation (mean_reward, accuracy, per-scaffold) is correct
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentanvil.adapter.agent_lightning import (
    ALRollout,
    ALTrainerStub,
    trajectory_to_al_rollout,
    trajectory_to_al_steps,
)
from agentanvil.trajectory import EventKind, Trajectory
from agentanvil.verifier.base import VerifyResult


def _toy_traj_with_tools(task_id="t1", reward_correct=True) -> tuple[Trajectory, VerifyResult]:
    t = Trajectory(task_id=task_id, scaffold="test-scaffold")
    t.emit(EventKind.OBSERVATION, {"text": "count the dots"})
    t.emit(EventKind.THOUGHT, {"text": "I'll use the counting tool."})
    t.emit(EventKind.TOOL_CALL, {"name": "count_dots", "arguments": {}, "call_id": "x1"})
    t.emit(EventKind.TOOL_RESULT, {"output": "3", "call_id": "x1"})
    t.emit(EventKind.FINAL_ANSWER, "ANSWER: 3")
    t.finish()
    vr = VerifyResult(
        correct=reward_correct,
        reward=1.0 if reward_correct else 0.0,
        parsed=3,
        gold=3 if reward_correct else 4,
        meta={"direction": "exact" if reward_correct else "undercount"},
    )
    return t, vr


def test_rollout_basic_conversion():
    traj, vr = _toy_traj_with_tools()
    r = trajectory_to_al_rollout(traj, vr)
    assert r.trajectory_id == traj.trajectory_id
    assert r.task_id == "t1"
    assert r.scaffold == "test-scaffold"
    assert r.prompt == "count the dots"
    assert r.response == "ANSWER: 3"
    assert r.reward == 1.0
    assert r.meta["correct"] is True
    assert r.meta["n_tool_calls"] == 1
    assert r.meta["direction"] == "exact"


def test_rollout_incorrect():
    traj, vr = _toy_traj_with_tools(reward_correct=False)
    r = trajectory_to_al_rollout(traj, vr)
    assert r.reward == 0.0
    assert r.meta["correct"] is False
    assert r.meta["direction"] == "undercount"


def test_steps_terminal_reward_only():
    traj, vr = _toy_traj_with_tools()
    steps = trajectory_to_al_steps(traj, vr)
    assert len(steps) >= 2
    assert all(s["reward"] == 0.0 for s in steps[:-1])
    assert steps[-1]["reward"] == 1.0
    assert steps[-1]["done"] is True
    assert all(not s["done"] for s in steps[:-1])


def test_trainer_aggregation_across_scaffolds():
    t1, v1 = _toy_traj_with_tools(task_id="a", reward_correct=True)
    t2 = Trajectory(task_id="b", scaffold="other-scaffold")
    t2.emit(EventKind.OBSERVATION, {"text": "x"})
    t2.emit(EventKind.FINAL_ANSWER, "ANSWER: 9")
    t2.finish()
    v2 = VerifyResult(correct=False, reward=0.0, parsed=9, gold=3, meta={"direction": "overcount"})

    tr = ALTrainerStub()
    tr.consume(trajectory_to_al_rollout(t1, v1))
    tr.consume(trajectory_to_al_rollout(t2, v2))
    rep = tr.report()
    assert rep["n"] == 2
    assert rep["mean_reward"] == 0.5
    assert rep["accuracy"] == 0.5
    assert set(rep["scaffolds"]) == {"test-scaffold", "other-scaffold"}
    assert rep["per_scaffold"]["test-scaffold"] == 1.0
    assert rep["per_scaffold"]["other-scaffold"] == 0.0


def test_trainer_empty_report():
    tr = ALTrainerStub()
    rep = tr.report()
    assert rep == {"n": 0, "mean_reward": 0.0, "accuracy": 0.0, "scaffolds": []}


if __name__ == "__main__":
    tests = [fn for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn)]
    passed = 0
    failed = []
    for fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            failed.append(fn.__name__)
            print(f"  ✗ {fn.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    if failed:
        sys.exit(1)
