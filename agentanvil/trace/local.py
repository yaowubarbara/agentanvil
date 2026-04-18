"""
Local JSONL sink.

Primary sink for Phase 0. Every trajectory appends one line. The replay UI
reads this file directly, so the harness is runnable end-to-end with zero
external services.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..trajectory import Trajectory
from ..verifier.base import VerifyResult
from .base import TraceSink


class LocalJsonlSink(TraceSink):
    def __init__(self, path: str | Path = "traces/traces.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, traj: Trajectory, verify_result: Optional[VerifyResult] = None) -> None:
        record = traj.to_json()
        if verify_result is not None:
            record["verify"] = {
                "verifier": verify_result.meta.get("verifier", None),
                "correct": verify_result.correct,
                "reward": verify_result.reward,
                "parsed": verify_result.parsed,
                "gold": verify_result.gold,
                "meta": verify_result.meta,
            }
        with self.path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")
