"""
Tests for the REAL Agent Lightning integration (not just the stub).

The real path calls `agentlightning.Trainer.fit()`. Since the lib may not be
installed in this env, we exercise:

  - AnvilLitAgent produces well-shaped rollouts
  - build_lit_agent returns AnvilLitAgent when lib is absent
  - train_with_agent_lightning falls back cleanly through ALTrainerStub
  - The fallback path produces the same accuracy report as the stub path
    (so trainers that DO have agent-lightning installed get consistent data)

When agent-lightning IS installed, an additional test auto-detects it and
verifies build_lit_agent returns a real LitAgent subclass.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentanvil.adapter.agent_lightning import (
    ALRollout,
    ALTrainerStub,
    AnvilLitAgent,
    build_lit_agent,
    train_with_agent_lightning,
    trajectory_to_al_rollout,
)
from agentanvil.agent import AnvilAgent, AnvilTask
from agentanvil.trajectory import EventKind, Trajectory
from agentanvil.verifier.base import VerifyResult, Verifier


# ── Fake agent + verifier ───────────────────────────────────────────

class _FakeAgent(AnvilAgent):
    scaffold_name = "fake-al"

    def __init__(self, answer_maker):
        self.answer_maker = answer_maker

    def run(self, task):
        t = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        t.emit(EventKind.OBSERVATION, task.initial_observation())
        t.emit(EventKind.THOUGHT, {"text": "thinking"})
        t.emit(EventKind.FINAL_ANSWER, self.answer_maker(task))
        t.finish()
        return t


class _FakeTask(AnvilTask):
    def __init__(self, tid, answer_expected):
        self.task_id = tid
        self.answer_expected = answer_expected

    def initial_observation(self):
        return {"text": f"task {self.task_id}"}


class _ExactMatchVerifier(Verifier):
    name = "exact_match"

    def verify(self, final_answer, task):
        correct = final_answer == task.answer_expected
        return VerifyResult(
            correct=correct,
            reward=1.0 if correct else 0.0,
            parsed=final_answer,
            gold=task.answer_expected,
            meta={"match_mode": "exact"},
        )


class _FakeDataset:
    def __init__(self, tasks):
        self.tasks = tasks

    def __iter__(self):
        return iter(self.tasks)

    def __len__(self):
        return len(self.tasks)


# ── Tests ───────────────────────────────────────────────────────────

def test_anvil_lit_agent_rollout_shape():
    agent = _FakeAgent(lambda t: t.answer_expected)
    verifier = _ExactMatchVerifier()
    task = _FakeTask("t1", "42")

    lit = AnvilLitAgent(agent, verifier)
    r = lit.rollout(task)

    assert isinstance(r, ALRollout)
    assert r.task_id == "t1"
    assert r.scaffold == "fake-al"
    assert r.response == "42"
    assert r.reward == 1.0
    assert r.meta["correct"] is True
    assert r.meta["rollout_idx"] == 1
    assert "trajectory" in r.meta   # full trace attached


def test_anvil_lit_agent_training_step_batches():
    agent = _FakeAgent(lambda t: t.answer_expected)
    verifier = _ExactMatchVerifier()
    batch = [_FakeTask(f"t{i}", str(i)) for i in range(3)]

    lit = AnvilLitAgent(agent, verifier)
    rollouts = lit.training_step(batch)
    assert len(rollouts) == 3
    assert [r.task_id for r in rollouts] == ["t0", "t1", "t2"]
    assert all(r.reward == 1.0 for r in rollouts)
    # idx should be 1, 2, 3
    assert [r.meta["rollout_idx"] for r in rollouts] == [1, 2, 3]


def test_build_lit_agent_returns_something_with_rollout():
    """Regardless of whether agent-lightning is installed, build_lit_agent
    must return an object implementing rollout()."""
    agent = _FakeAgent(lambda t: "x")
    verifier = _ExactMatchVerifier()
    lit = build_lit_agent(agent, verifier)
    assert hasattr(lit, "rollout")
    assert callable(lit.rollout)


def test_train_fallback_to_stub_runs_full_dataset():
    agent = _FakeAgent(lambda t: t.answer_expected)   # always correct
    verifier = _ExactMatchVerifier()
    dataset = _FakeDataset([_FakeTask(f"t{i}", str(i)) for i in range(7)])

    result = train_with_agent_lightning(
        agent, verifier, dataset, max_epochs=1, batch_size=3, fallback_to_stub=True
    )
    assert result["path"] == "stub"
    report = result["report"]
    assert report["n"] == 7
    assert report["accuracy"] == 1.0
    assert report["scaffolds"] == ["fake-al"]


def test_train_fallback_tracks_mixed_accuracy():
    # Agent is correct only on even task ids
    def answer(t):
        return t.answer_expected if int(t.task_id[1:]) % 2 == 0 else "wrong"

    agent = _FakeAgent(answer)
    verifier = _ExactMatchVerifier()
    dataset = _FakeDataset([_FakeTask(f"t{i}", str(i)) for i in range(10)])

    result = train_with_agent_lightning(
        agent, verifier, dataset, max_epochs=1, batch_size=4, fallback_to_stub=True
    )
    report = result["report"]
    assert report["n"] == 10
    # Correct on even tids (0,2,4,6,8) → 5/10 = 0.5
    assert abs(report["accuracy"] - 0.5) < 1e-9


def test_train_no_fallback_raises_when_lib_absent():
    try:
        import agentlightning  # noqa: F401

        return  # lib IS present — skip the negative test
    except ImportError:
        pass
    agent = _FakeAgent(lambda t: "x")
    verifier = _ExactMatchVerifier()
    dataset = _FakeDataset([_FakeTask("t0", "x")])
    try:
        train_with_agent_lightning(
            agent, verifier, dataset, fallback_to_stub=False
        )
    except ImportError as e:
        assert "agent-lightning" in str(e)
        return
    raise AssertionError("expected ImportError when agent-lightning absent and fallback disabled")


def test_build_lit_agent_real_when_installed():
    """If agent-lightning is installed, build_lit_agent returns a real subclass."""
    try:
        from agentlightning import LitAgent  # noqa
    except ImportError:
        return  # lib absent — nothing to assert here

    agent = _FakeAgent(lambda t: "x")
    verifier = _ExactMatchVerifier()
    lit = build_lit_agent(agent, verifier)
    assert isinstance(lit, LitAgent), f"expected LitAgent subclass, got {type(lit)}"


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn)]
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {name}")
        except AssertionError as e:
            failed.append((name, str(e)))
            print(f"  ✗ {name}: {e}")
        except Exception as e:
            failed.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    if failed:
        sys.exit(1)
