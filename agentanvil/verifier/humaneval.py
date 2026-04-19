"""
HumanEval verifier (Chen et al. 2021, OpenAI).

HumanEval ships a `prompt` (function signature + docstring), a `canonical_solution`,
and `test` code that defines a `check(candidate)` function asserting behavior.
Scoring is pass@1: does the model's completion, when combined with the prompt
and run with the test, make `check(...)` pass?

Safety choice:
  Executing model-generated code is a real security concern. This verifier
  runs the candidate in a subprocess with a wall-clock timeout. It does NOT
  provide seccomp or filesystem isolation — pair it with the Rust supervisor
  or OpenSandbox runtime when running on untrusted models.

Parse contract:
  The model must emit its completion inside a fenced code block OR after a
  "SOLUTION:" marker. The verifier is strict: no heuristic salvaging of raw
  Python snippets from narrative text.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from typing import Optional

from .base import Verifier, VerifyResult

_CODE_FENCE_RE = re.compile(r"```(?:python)?\n(.*?)```", re.DOTALL)
_SOLUTION_RE = re.compile(r"SOLUTION:\s*\n(.*?)(?:\n\n|$)", re.DOTALL | re.IGNORECASE)


def _extract_completion(output: str) -> Optional[str]:
    if not output:
        return None
    fences = _CODE_FENCE_RE.findall(output)
    if fences:
        return fences[-1].strip()
    sol = _SOLUTION_RE.search(output)
    if sol:
        return sol.group(1).strip()
    return None


@dataclass
class HumanEvalTask:
    task_id: str
    prompt: str
    test_code: str
    entry_point: str
    canonical_solution: Optional[str] = None

    def initial_observation(self) -> dict:
        return {
            "text": (
                "Complete the following Python function. Output your completion "
                "inside a single ```python ... ``` code block. The completion "
                "should be the function body (no signature, no imports that aren't "
                "in the prompt).\n\n"
                f"```python\n{self.prompt}\n```"
            )
        }


class HumanEvalVerifier(Verifier):
    name = "humaneval"

    def __init__(self, timeout_seconds: int = 10):
        self.timeout_seconds = timeout_seconds

    def verify(self, final_answer: str, task: HumanEvalTask) -> VerifyResult:
        completion = _extract_completion(final_answer)
        if completion is None:
            return VerifyResult(
                correct=False,
                reward=0.0,
                parsed=None,
                gold=task.entry_point,
                meta={"parse_failed": True, "reason": "no code fence / SOLUTION marker"},
            )
        # Assemble the runner explicitly (no textwrap.dedent — the injected
        # prompt/completion/test_code already have their own indentation, and
        # dedent would misalign them).
        if completion.lstrip().startswith(("def ", "class ", "import ", "from ")):
            body_or_full = completion
        else:
            body_or_full = task.prompt.rstrip() + "\n" + textwrap.indent(completion, "    ")
        runner = (
            "import sys, signal\n"
            f"signal.alarm({self.timeout_seconds})\n"
            f"{body_or_full}\n"
            f"{task.test_code}\n"
            f"check({task.entry_point})\n"
            'print("HUMANEVAL_OK")\n'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(runner)
            runner_path = f.name
        try:
            result = subprocess.run(
                [sys.executable, runner_path],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds + 2,
            )
            passed = result.returncode == 0 and "HUMANEVAL_OK" in (result.stdout or "")
            return VerifyResult(
                correct=passed,
                reward=1.0 if passed else 0.0,
                parsed=completion[:200] + ("..." if len(completion) > 200 else ""),
                gold=task.entry_point,
                meta={
                    "parse_failed": False,
                    "returncode": result.returncode,
                    "stderr_head": (result.stderr or "")[:300],
                    "stdout_head": (result.stdout or "")[:300],
                },
            )
        except subprocess.TimeoutExpired:
            return VerifyResult(
                correct=False,
                reward=0.0,
                parsed=completion[:200],
                gold=task.entry_point,
                meta={"timeout": True, "seconds": self.timeout_seconds},
            )
        finally:
            try:
                os.unlink(runner_path)
            except OSError:
                pass
