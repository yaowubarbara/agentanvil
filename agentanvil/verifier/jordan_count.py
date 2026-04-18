"""
Jordan Count verifier.

Mirrors the evaluation methodology of github.com/yaowubarbara/jordan-count:
  - Strict ANSWER: <integer> parser (plus a tolerant "bare integer" branch).
  - No heuristic repair of malformed outputs.
  - Binary reward: 1 if parsed == gold, else 0.

The task carries its own gold_count (computed offline via the crossing-number
algorithm over the curve + labeled dots). Keeping the gold with the task lets
us swap in tasks from the reference repo, hand-authored samples, or a future
online generator without touching the verifier.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .base import Verifier, VerifyResult

_ANSWER_RE = re.compile(r"ANSWER\s*:\s*(-?\d+)", re.IGNORECASE)
_BARE_INT_RE = re.compile(r"^\s*(-?\d+)\s*$")


@dataclass
class JordanCountTask:
    """Minimal Jordan Count problem payload.

    Phase 0 ships with hand-authored sample tasks under examples/sample_tasks/;
    Phase 1 will add a loader that reads from the upstream jordan-count repo's
    JSON dump so we can track the published benchmark exactly.
    """

    task_id: str
    image_path: Optional[str]
    gold_count: int
    dots: list = None
    curve_points: list = None
    prompt: str = (
        "Count how many of the numbered dots lie strictly inside the closed curve. "
        "Respond in the exact form 'ANSWER: <integer>' on the final line. "
        "Do not include any other integers in your final line."
    )

    def initial_observation(self) -> dict:
        return {"text": self.prompt, "image_path": self.image_path}


class JordanCountVerifier(Verifier):
    name = "jordan_count"

    def parse(self, output: str) -> Optional[int]:
        if not output:
            return None
        m = _ANSWER_RE.search(output)
        if m:
            return int(m.group(1))
        m = _BARE_INT_RE.match(output.strip())
        if m:
            return int(m.group(1))
        return None

    def verify(self, final_answer: str, task: JordanCountTask) -> VerifyResult:
        parsed = self.parse(final_answer)
        gold = task.gold_count
        correct = parsed is not None and parsed == gold
        return VerifyResult(
            correct=correct,
            reward=1.0 if correct else 0.0,
            parsed=parsed,
            gold=gold,
            meta={
                "parse_failed": parsed is None,
                "direction": None if parsed is None else (
                    "overcount" if parsed > gold else "undercount" if parsed < gold else "exact"
                ),
            },
        )
