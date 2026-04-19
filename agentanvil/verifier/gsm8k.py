"""
GSM8K verifier.

GSM8K (Grade School Math 8K, Cobbe et al. 2021) is a benchmark of grade-school
math word problems. The canonical answer format is a single integer at the
end of the reasoning trace, preceded by "####". Example gold:

    "... 4 hours total. #### 4"

Matching the official Cobbe et al. evaluation:
  - Extract the integer that follows the LAST "####" in the model's output.
  - Fall back to the LAST integer in the output if no "####" marker.
  - Parse gold the same way — gold strings may also contain reasoning.

Strict vs tolerant parsing is exposed via `strict=True` kwarg:
  strict=True  -> require "#### N" marker; missing marker = wrong.
  strict=False -> accept last-integer fallback (matches many public evals).

Default is strict=False to match the de-facto evaluation standard used by
most published GSM8K numbers, but a strict run is one flag away for teams
that want cleaner RLVR reward signal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .base import Verifier, VerifyResult

_HASH_MARKER_RE = re.compile(r"####\s*(-?\d+(?:,\d{3})*(?:\.\d+)?)")
_LAST_INT_RE = re.compile(r"(-?\d+(?:,\d{3})*(?:\.\d+)?)")


def _parse_number(s: str, strict: bool = False) -> Optional[float]:
    if not s:
        return None
    matches = _HASH_MARKER_RE.findall(s)
    if matches:
        tok = matches[-1].replace(",", "")
        try:
            val = float(tok)
            return val
        except ValueError:
            return None
    if strict:
        return None
    matches = _LAST_INT_RE.findall(s)
    if matches:
        tok = matches[-1].replace(",", "")
        try:
            return float(tok)
        except ValueError:
            return None
    return None


@dataclass
class GSM8KTask:
    task_id: str
    question: str
    gold_answer: str
    image_path: Optional[str] = None

    def initial_observation(self) -> dict:
        prompt = (
            f"{self.question}\n\n"
            "Think step by step, then on the final line write '#### <integer>' "
            "with your final numeric answer."
        )
        return {"text": prompt}


class GSM8KVerifier(Verifier):
    name = "gsm8k"

    def __init__(self, strict: bool = False, tolerance: float = 1e-9):
        self.strict = strict
        self.tolerance = tolerance

    def verify(self, final_answer: str, task: GSM8KTask) -> VerifyResult:
        parsed = _parse_number(final_answer, strict=self.strict)
        gold = _parse_number(task.gold_answer, strict=False)
        correct = False
        if parsed is not None and gold is not None:
            correct = abs(parsed - gold) <= self.tolerance
        return VerifyResult(
            correct=correct,
            reward=1.0 if correct else 0.0,
            parsed=parsed,
            gold=gold,
            meta={
                "strict": self.strict,
                "parse_failed": parsed is None,
                "gold_parse_failed": gold is None,
                "marker_used": "####" if _HASH_MARKER_RE.search(final_answer or "") else "last_int",
            },
        )
