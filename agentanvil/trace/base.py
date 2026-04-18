from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..trajectory import Trajectory
from ..verifier.base import VerifyResult


class TraceSink(ABC):
    @abstractmethod
    def write(self, traj: Trajectory, verify_result: Optional[VerifyResult] = None) -> None: ...
