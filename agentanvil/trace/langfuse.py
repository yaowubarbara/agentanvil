"""
Langfuse sink.

Emits one trace per trajectory, with nested spans per event and a score for
the verifier reward. Requires env vars:
  - LANGFUSE_PUBLIC_KEY
  - LANGFUSE_SECRET_KEY
  - LANGFUSE_HOST  (e.g. http://localhost:3000 for self-host)

Phase 0 uses the langfuse v2 SDK surface; Phase 1 will lock the SDK major
version and add token accounting + latency breakdowns.
"""
from __future__ import annotations

from typing import Optional

from ..trajectory import EventKind, Trajectory
from ..verifier.base import VerifyResult
from .base import TraceSink


class LangfuseSink(TraceSink):
    def __init__(self):
        try:
            from langfuse import Langfuse
        except ImportError as e:
            raise ImportError(
                "Install with `pip install agentanvil[langfuse]` to use LangfuseSink"
            ) from e
        self.client = Langfuse()

    def write(self, traj: Trajectory, verify_result: Optional[VerifyResult] = None) -> None:
        trace = self.client.trace(
            id=traj.trajectory_id,
            name=f"{traj.scaffold}/{traj.task_id}",
            metadata={"scaffold": traj.scaffold, "task_id": traj.task_id, **traj.meta},
        )
        for e in traj.events:
            output = e.content if isinstance(e.content, (str, int, float, dict, list)) else str(e.content)
            trace.span(
                name=e.kind.value,
                input={"step": e.step},
                output=output,
                metadata=e.meta,
            )
        if verify_result is not None:
            trace.score(
                name="reward",
                value=float(verify_result.reward),
                comment=(
                    f"correct={verify_result.correct} parsed={verify_result.parsed} "
                    f"gold={verify_result.gold}"
                ),
            )
        self.client.flush()
