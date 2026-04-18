"""
AnvilAgent: the protocol every scaffold adapter implements.

Phase 0 uses a single-shot `run(task) -> Trajectory` interface. This is enough
for verifiable, episodic tasks (Jordan Count, SWE-bench-lite).

Phase 1+ may add interactive forms (step/reset) for environments with long
tool loops or human-in-the-loop; adapters that need those will implement
them as extensions — the single-shot `run` stays the stable contract.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .trajectory import Trajectory


class AnvilTask(ABC):
    """A verifiable task. Subclasses carry whatever payload the verifier needs."""

    task_id: str

    @abstractmethod
    def initial_observation(self) -> dict:
        """Return the first observation presented to the agent.

        Convention: {"text": str, "image_path": Optional[str], ...}
        Adapters pick what they can consume; extra keys are ignored.
        """


class AnvilAgent(ABC):
    """Implement this in each adapter. One method, stable contract."""

    scaffold_name: str = "unknown"

    @abstractmethod
    def run(self, task: AnvilTask) -> Trajectory:
        """Execute the agent on a task and return the full trajectory."""
