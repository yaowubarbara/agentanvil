"""
Seed demo traces for the diff UI.

Writes two trajectories on the SAME task_id ("suite/jc_000") with DIFFERENT
scaffolds, so the diff UI has canonical content to show side-by-side without
burning any API credit:

  - claude-code : replayed from tests/fixtures/claude_code_sample.jsonl,
                  ends with "ANSWER: 3" → verifier says correct.
  - minimal     : stubbed with "ANSWER: 4" → verifier says overcount (the
                  canonical Sonnet failure mode on boundary-adjacent dots,
                  documented in the Jordan Count paper).

This gives the diff UI a realistic contrast: one scaffold reasoned through
a tool call and landed on the right answer; the other jumped straight to a
wrong integer. Same task, divergent trajectories — exactly what cross-
scaffold evaluation is for.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentanvil import AnvilAgent, AnvilTask, run_one
from agentanvil.adapter.claude_code import ClaudeCodeAdapter
from agentanvil.trajectory import EventKind, Trajectory
from agentanvil.trace.local import LocalJsonlSink
from agentanvil.verifier.jordan_count import JordanCountTask, JordanCountVerifier


TASK_ID = "suite/jc_000"
GOLD = 3
TRACES_PATH = Path(__file__).resolve().parents[1] / "traces" / "traces.jsonl"


class _ReplayClaudeCode(AnvilAgent):
    """Pretends to be Claude Code by replaying a recorded stream-json fixture
    under a caller-specified task_id, preserving the scaffold identity and
    the full tool-use trajectory shape."""

    scaffold_name = "claude-code"

    def __init__(self, fixture_path: Path, task_id: str):
        self.fixture_path = fixture_path
        self.task_id = task_id

    def run(self, task: AnvilTask) -> Trajectory:
        replayed = ClaudeCodeAdapter.from_stream(self.fixture_path, task_id=self.task_id)
        replayed.events[0] = type(replayed.events[0])(
            kind=EventKind.OBSERVATION,
            content=task.initial_observation(),
            step=0,
            ts=replayed.events[0].ts,
            meta=replayed.events[0].meta,
        )
        return replayed


class _OvercountStub(AnvilAgent):
    scaffold_name = "minimal"

    def __init__(self, answer: str):
        self.answer = answer

    def run(self, task: AnvilTask) -> Trajectory:
        t = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        t.emit(EventKind.OBSERVATION, task.initial_observation())
        t.emit(
            EventKind.THOUGHT,
            {"text": "I'll count the dots by eyeballing the image."},
        )
        t.emit(EventKind.FINAL_ANSWER, self.answer, model="stub", provider="stub")
        t.finish()
        return t


def main():
    TRACES_PATH.unlink(missing_ok=True)
    TRACES_PATH.parent.mkdir(parents=True, exist_ok=True)
    sink = LocalJsonlSink(TRACES_PATH)
    verifier = JordanCountVerifier()

    task = JordanCountTask(task_id=TASK_ID, image_path=None, gold_count=GOLD)

    fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "claude_code_sample.jsonl"
    cc_agent = _ReplayClaudeCode(fixture, TASK_ID)
    mini_agent = _OvercountStub(answer=f"ANSWER: {GOLD + 1}")

    cc_traj, cc_result = run_one(cc_agent, task, verifier, [sink])
    mi_traj, mi_result = run_one(mini_agent, task, verifier, [sink])

    print(f"Seeded {TRACES_PATH}")
    print(f"  claude-code: id={cc_traj.trajectory_id} events={len(cc_traj.events)} parsed={cc_result.parsed} correct={cc_result.correct}")
    print(f"  minimal:     id={mi_traj.trajectory_id} events={len(mi_traj.events)} parsed={mi_result.parsed} correct={mi_result.correct} dir={mi_result.meta.get('direction')}")
    print()
    print(f"Diff URL: /diff?a={cc_traj.trajectory_id}&b={mi_traj.trajectory_id}")


if __name__ == "__main__":
    main()
