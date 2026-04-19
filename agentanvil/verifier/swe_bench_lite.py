"""
SWE-bench Lite verifier (stub).

SWE-bench (Jimenez et al. 2023) asks an agent to produce a git diff that, when
applied to a real GitHub repo at a pinned commit, makes previously failing
tests pass. Full SWE-bench scoring requires a Docker-based reproduction
environment for each task; SWE-bench Lite is a curated subset designed for
faster iteration.

Full reproduction is out of scope for this verifier — running untrusted
patches against real repos is heavy and must live in a sandboxed runtime.
What we DO here is the lightweight surface that makes the harness usable:

  - parse: extract a unified-diff patch from the model's output
  - gold:  compare against the canonical patch by heuristic overlap
           (filenames touched, number of hunks, byte-length ratio)
  - score: binary (strict filename match + non-zero hunks) OR scalar
           (weighted overlap) selectable via `binary=True|False`

Replace `reward` with a real pass@1 via `swebench.harness` integration when
you're ready to spin Docker containers per task. The `parse` output is the
same diff string, so the trainer's contract doesn't change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .base import Verifier, VerifyResult

_DIFF_FENCE_RE = re.compile(r"```(?:diff|patch)?\n(.*?)```", re.DOTALL)
_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
_HUNK_RE = re.compile(r"^@@ ", re.MULTILINE)


def _extract_patch(output: str) -> Optional[str]:
    if not output:
        return None
    fences = _DIFF_FENCE_RE.findall(output)
    if fences:
        for chunk in reversed(fences):
            if "diff --git" in chunk or chunk.lstrip().startswith(("---", "+++")):
                return chunk.strip()
    if "diff --git" in output:
        idx = output.index("diff --git")
        return output[idx:].strip()
    return None


def _patch_stats(patch: str) -> dict:
    files = [m.group(1) for m in _DIFF_HEADER_RE.finditer(patch)]
    hunks = len(_HUNK_RE.findall(patch))
    return {"files": files, "n_files": len(files), "n_hunks": hunks, "bytes": len(patch)}


@dataclass
class SWEBenchLiteTask:
    task_id: str
    repo: str
    base_commit: str
    problem_statement: str
    gold_patch: str
    fail_to_pass: list = field(default_factory=list)
    pass_to_pass: list = field(default_factory=list)

    def initial_observation(self) -> dict:
        return {
            "text": (
                f"Repository: {self.repo} @ {self.base_commit}\n\n"
                f"{self.problem_statement}\n\n"
                "Produce a unified diff patch (```diff ... ```) that fixes the issue. "
                "Do not include commentary — the patch must apply cleanly with `git apply`."
            )
        }


class SWEBenchLiteVerifier(Verifier):
    name = "swe_bench_lite"

    def __init__(self, binary: bool = False):
        """
        binary=True  -> reward is 1.0 iff filenames match exactly AND patch has
                        >=1 hunk (harshest lightweight signal).
        binary=False -> reward is weighted overlap score in [0, 1].
        """
        self.binary = binary

    def verify(self, final_answer: str, task: SWEBenchLiteTask) -> VerifyResult:
        patch = _extract_patch(final_answer)
        if patch is None:
            return VerifyResult(
                correct=False,
                reward=0.0,
                parsed=None,
                gold=_patch_stats(task.gold_patch),
                meta={"parse_failed": True, "reason": "no diff fence"},
            )

        pred_stats = _patch_stats(patch)
        gold_stats = _patch_stats(task.gold_patch)

        pred_files = set(pred_stats["files"])
        gold_files = set(gold_stats["files"])
        file_jaccard = (
            len(pred_files & gold_files) / len(pred_files | gold_files)
            if (pred_files or gold_files)
            else 0.0
        )
        hunk_ratio = min(pred_stats["n_hunks"], gold_stats["n_hunks"]) / max(
            pred_stats["n_hunks"], gold_stats["n_hunks"], 1
        )
        size_ratio = min(pred_stats["bytes"], gold_stats["bytes"]) / max(
            pred_stats["bytes"], gold_stats["bytes"], 1
        )
        overlap = 0.5 * file_jaccard + 0.3 * hunk_ratio + 0.2 * size_ratio

        if self.binary:
            correct = (pred_files == gold_files) and pred_stats["n_hunks"] >= 1
            reward = 1.0 if correct else 0.0
        else:
            correct = file_jaccard >= 0.5
            reward = float(overlap)

        return VerifyResult(
            correct=correct,
            reward=reward,
            parsed=pred_stats,
            gold=gold_stats,
            meta={
                "parse_failed": False,
                "binary_mode": self.binary,
                "file_jaccard": file_jaccard,
                "hunk_ratio": hunk_ratio,
                "size_ratio": size_ratio,
                "overlap": overlap,
                "note": "Lightweight verifier. For pass@1 on real fail_to_pass tests, integrate swebench.harness (Docker per task).",
            },
        )
