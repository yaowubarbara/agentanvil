"""
Top-level orchestrator.

Takes an agent + task + verifier + trace sinks, runs the pipeline, returns
(trajectory, verify_result). Verifier reward is appended to the trajectory
as a REWARD event before sinks see it — so every downstream consumer
(Langfuse, UI, RL trainer) has reward in-line with the events.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .agent import AnvilAgent, AnvilTask
from .trajectory import EventKind
from .trace.base import TraceSink
from .verifier.base import Verifier, VerifyResult


def run_one(
    agent: AnvilAgent,
    task: AnvilTask,
    verifier: Verifier,
    sinks: Iterable[TraceSink] = (),
) -> tuple:
    traj = agent.run(task)
    final = traj.final_answer() or ""
    result = verifier.verify(final, task)
    result.meta.setdefault("verifier", verifier.name)
    traj.emit(
        EventKind.REWARD,
        {
            "reward": result.reward,
            "correct": result.correct,
            "parsed": result.parsed,
            "gold": result.gold,
            "verifier": verifier.name,
        },
    )
    for sink in sinks:
        sink.write(traj, result)
    return traj, result
