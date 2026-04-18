"""
Verifier contract.

A Verifier takes a final answer string + the task, and produces a VerifyResult.

Principle: strict parsing. If the agent did not produce output in the contracted
format, parsed is None and correct is False. We do not heuristically repair.
This keeps reward signal clean for RL and keeps benchmarks honest.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VerifyResult:
    correct: bool
    reward: float
    parsed: Any
    gold: Any
    meta: dict = field(default_factory=dict)


class Verifier(ABC):
    name: str = "unknown"

    @abstractmethod
    def verify(self, final_answer: str, task) -> VerifyResult: ...
