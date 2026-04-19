"""
Evaluator framework.

A Verifier answers "did the agent get the right answer?". An Evaluator answers
richer questions: "how well did the agent do it?" — reasoning quality, format
compliance, safety, style, etc. Verifiers produce a single binary reward;
Evaluators can produce any number of named scalar or categorical scores.

Three categories of evaluator ship in-box:

  1. ProgrammaticEvaluator — pure-code checks (regex presence, answer length,
     contains required keywords, no profanity list hit). Fast, deterministic,
     zero cost.
  2. RubricEvaluator         — weighted sum of programmatic checks against a
     named rubric. Lets you assemble a multi-criterion score without calling
     an LLM.
  3. LLMJudgeEvaluator       — uses a Claude / GPT judge model to score on a
     scalar 1-5 scale with structured output. Expensive but captures nuances
     no regex can (politeness, correctness of reasoning chain, etc.).

All three return EvalScore objects with compatible shape, so a downstream
pipeline can mix-and-match. Scores are attached to a trajectory via the REWARD
event's `meta.scores` dict (one entry per evaluator that ran).
"""
from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional


@dataclass
class EvalScore:
    name: str
    value: float          # typically in [0, 1]; rubric scores can exceed
    label: Optional[str] = None   # categorical (e.g. "pass"/"fail", "1-of-5")
    reasoning: Optional[str] = None
    meta: dict = field(default_factory=dict)


class Evaluator(ABC):
    name: str = "unknown"

    @abstractmethod
    def score(self, final_answer: str, task: Any = None, trajectory: Any = None) -> EvalScore: ...


# ── Programmatic evaluators ─────────────────────────────────────────

class ContainsKeywordsEvaluator(Evaluator):
    """1.0 iff ALL required keywords appear in final_answer (case-insensitive)."""

    def __init__(self, keywords: Iterable[str], name: str = "contains_keywords"):
        self.keywords = [k.lower() for k in keywords]
        self.name = name

    def score(self, final_answer: str, task=None, trajectory=None) -> EvalScore:
        low = (final_answer or "").lower()
        hits = [k for k in self.keywords if k in low]
        value = len(hits) / len(self.keywords) if self.keywords else 1.0
        return EvalScore(
            name=self.name,
            value=value,
            label="all" if value == 1.0 else "partial" if value > 0 else "none",
            meta={"hits": hits, "missing": [k for k in self.keywords if k not in hits]},
        )


class RegexEvaluator(Evaluator):
    """Score 1.0 iff regex matches; 0.0 otherwise. Returns match groups in meta."""

    def __init__(self, pattern: str, flags: int = 0, name: str = "regex_match"):
        self.regex = re.compile(pattern, flags)
        self.pattern = pattern
        self.name = name

    def score(self, final_answer: str, task=None, trajectory=None) -> EvalScore:
        m = self.regex.search(final_answer or "")
        if m is None:
            return EvalScore(name=self.name, value=0.0, label="no-match", meta={"pattern": self.pattern})
        return EvalScore(
            name=self.name,
            value=1.0,
            label="match",
            meta={"pattern": self.pattern, "match": m.group(0), "groups": list(m.groups())},
        )


class LengthBandEvaluator(Evaluator):
    """1.0 if final_answer length is within [min, max] chars, else 0.0."""

    def __init__(self, min_chars: int, max_chars: int, name: str = "length_band"):
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.name = name

    def score(self, final_answer: str, task=None, trajectory=None) -> EvalScore:
        n = len(final_answer or "")
        ok = self.min_chars <= n <= self.max_chars
        label = "in_band" if ok else ("too_short" if n < self.min_chars else "too_long")
        return EvalScore(
            name=self.name,
            value=1.0 if ok else 0.0,
            label=label,
            meta={"length": n, "min": self.min_chars, "max": self.max_chars},
        )


class NoForbiddenWordsEvaluator(Evaluator):
    """1.0 iff NONE of the forbidden words appear. Useful as a safety check."""

    def __init__(self, forbidden: Iterable[str], name: str = "no_forbidden"):
        self.forbidden = [w.lower() for w in forbidden]
        self.name = name

    def score(self, final_answer: str, task=None, trajectory=None) -> EvalScore:
        low = (final_answer or "").lower()
        hits = [w for w in self.forbidden if w in low]
        value = 1.0 if not hits else 0.0
        return EvalScore(
            name=self.name,
            value=value,
            label="clean" if value == 1.0 else "violation",
            meta={"hits": hits},
        )


class TrajectoryShapeEvaluator(Evaluator):
    """Score based on trajectory structure, not final answer.

    Useful signals:
      - `min_tool_calls`: reward at least N tool_call events
      - `max_tool_calls`: penalize over-N tool_calls (loops)
      - `require_kind`:   require at least one event of a given kind
    """

    def __init__(
        self,
        min_tool_calls: int = 0,
        max_tool_calls: Optional[int] = None,
        require_kind: Optional[str] = None,
        name: str = "trajectory_shape",
    ):
        self.min_tool_calls = min_tool_calls
        self.max_tool_calls = max_tool_calls
        self.require_kind = require_kind
        self.name = name

    def score(self, final_answer: str, task=None, trajectory=None) -> EvalScore:
        if trajectory is None:
            return EvalScore(name=self.name, value=0.0, label="no_trajectory", meta={})
        events = trajectory.events if hasattr(trajectory, "events") else (trajectory.get("events") or [])
        n_tool_calls = sum(
            1 for e in events
            if (getattr(e, "kind", None) and e.kind.value == "tool_call")
            or (isinstance(e, dict) and e.get("kind") == "tool_call")
        )
        checks = []
        if n_tool_calls < self.min_tool_calls:
            checks.append(("below_min_tool_calls", False))
        else:
            checks.append(("above_min_tool_calls", True))
        if self.max_tool_calls is not None and n_tool_calls > self.max_tool_calls:
            checks.append(("exceeds_max_tool_calls", False))
        else:
            checks.append(("within_max_tool_calls", True))
        if self.require_kind is not None:
            present = any(
                (getattr(e, "kind", None) and e.kind.value == self.require_kind)
                or (isinstance(e, dict) and e.get("kind") == self.require_kind)
                for e in events
            )
            checks.append((f"has_{self.require_kind}", present))
        n_pass = sum(1 for _, ok in checks if ok)
        value = n_pass / len(checks) if checks else 1.0
        return EvalScore(
            name=self.name,
            value=value,
            label="all_pass" if value == 1.0 else "partial",
            meta={
                "n_tool_calls": n_tool_calls,
                "checks": dict(checks),
            },
        )


# ── Rubric ──────────────────────────────────────────────────────────

@dataclass
class RubricCriterion:
    name: str
    weight: float
    evaluator: Evaluator


class RubricEvaluator(Evaluator):
    """Weighted sum over named sub-evaluators.

    Example:
        rubric = RubricEvaluator("quality", [
            RubricCriterion("has_answer_format", 0.5, RegexEvaluator(r"ANSWER:\\s*\\d+")),
            RubricCriterion("brief", 0.3, LengthBandEvaluator(0, 500)),
            RubricCriterion("safe",  0.2, NoForbiddenWordsEvaluator(["hack", "exploit"])),
        ])
    """

    def __init__(self, name: str, criteria: Iterable[RubricCriterion]):
        self.name = name
        self.criteria = list(criteria)
        total_weight = sum(c.weight for c in self.criteria)
        if total_weight <= 0:
            raise ValueError("Rubric weights must sum to > 0")
        self._normalizer = total_weight

    def score(self, final_answer: str, task=None, trajectory=None) -> EvalScore:
        sub: dict[str, EvalScore] = {}
        weighted_sum = 0.0
        for c in self.criteria:
            s = c.evaluator.score(final_answer, task=task, trajectory=trajectory)
            sub[c.name] = s
            weighted_sum += c.weight * s.value
        value = weighted_sum / self._normalizer
        return EvalScore(
            name=self.name,
            value=value,
            meta={
                "sub_scores": {
                    name: {"value": s.value, "label": s.label, "weight": c.weight}
                    for name, (s, c) in zip(sub, zip(sub.values(), self.criteria))
                },
                "normalizer": self._normalizer,
            },
        )


# ── LLM-as-judge ─────────────────────────────────────────────────────

JUDGE_PROMPT_TEMPLATE = """You are an evaluator scoring an AI agent's final answer.

Task: {task_description}
Expected answer (if known): {expected}
Agent's answer:
{final_answer}

Scoring criterion: {criterion}

Give a score from 1 (worst) to 5 (best) and a one-sentence reason.

Respond in this exact format:
SCORE: <int 1-5>
REASON: <one sentence>"""


class LLMJudgeEvaluator(Evaluator):
    """Use a Claude or OpenAI model as judge.

    The judge prompt is small + deterministic: "score 1-5 with one-sentence
    reason". Output is parsed strictly; malformed outputs score 0.

    Cost-conscious defaults:
      - model defaults to Haiku (or gpt-5-nano) — judge models don't need to
        be as strong as the task-executing model.
      - max_tokens defaults to 128 — enough for 'SCORE: 5\\nREASON: ...'.

    Usage:
        judge = LLMJudgeEvaluator(
            criterion="reasoning chain is correct step-by-step",
            provider="anthropic",
        )
        score = judge.score(final_answer, task=task)
    """

    SCORE_RE = re.compile(r"SCORE:\s*([1-5])", re.IGNORECASE)
    REASON_RE = re.compile(r"REASON:\s*(.+?)(?:\n|$)", re.IGNORECASE | re.DOTALL)

    def __init__(
        self,
        criterion: str,
        provider: str = "anthropic",
        model: Optional[str] = None,
        max_tokens: int = 128,
        name: Optional[str] = None,
        call_fn: Optional[Callable[[str], str]] = None,
    ):
        self.criterion = criterion
        self.provider = provider
        self.model = model or ("claude-haiku-4-5" if provider == "anthropic" else "gpt-5-nano")
        self.max_tokens = max_tokens
        self.name = name or f"judge:{criterion[:40]}"
        self.call_fn = call_fn   # for tests: inject a stub

    def score(self, final_answer: str, task: Any = None, trajectory=None) -> EvalScore:
        task_desc = ""
        expected = "(not provided)"
        if task is not None:
            if hasattr(task, "question"):
                task_desc = task.question
            elif hasattr(task, "prompt"):
                task_desc = str(task.prompt)[:500]
            elif hasattr(task, "task_id"):
                task_desc = f"task_id={task.task_id}"
            if hasattr(task, "gold_answer"):
                expected = str(task.gold_answer)
            elif hasattr(task, "gold_count"):
                expected = str(task.gold_count)

        prompt = JUDGE_PROMPT_TEMPLATE.format(
            task_description=task_desc or "(see agent's answer)",
            expected=expected,
            final_answer=(final_answer or "")[:2000],
            criterion=self.criterion,
        )

        if self.call_fn is not None:
            response_text = self.call_fn(prompt)
        else:
            try:
                response_text = self._call_llm(prompt)
            except Exception as e:
                return EvalScore(
                    name=self.name,
                    value=0.0,
                    label="error",
                    meta={"error": type(e).__name__, "message": str(e)},
                )

        score_m = self.SCORE_RE.search(response_text or "")
        reason_m = self.REASON_RE.search(response_text or "")
        if score_m is None:
            return EvalScore(
                name=self.name,
                value=0.0,
                label="parse_fail",
                reasoning=response_text[:200],
                meta={"raw": response_text, "criterion": self.criterion},
            )
        raw = int(score_m.group(1))
        norm = (raw - 1) / 4.0   # 1→0, 5→1
        return EvalScore(
            name=self.name,
            value=norm,
            label=f"{raw}/5",
            reasoning=(reason_m.group(1).strip() if reason_m else None),
            meta={"raw_score": raw, "criterion": self.criterion, "judge_model": self.model},
        )

    def _call_llm(self, prompt: str) -> str:
        if self.provider == "anthropic":
            import anthropic

            client = anthropic.Anthropic()
            resp = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if self.provider == "openai":
            import openai

            client = openai.OpenAI()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
            )
            return (resp.choices[0].message.content or "").strip()
        raise ValueError(f"Unknown provider: {self.provider}")


# ── Registry ─────────────────────────────────────────────────────────

class EvaluatorRegistry:
    """Run many evaluators on the same answer/trajectory; return score dict.

    Usage:
        reg = EvaluatorRegistry()
        reg.add(RegexEvaluator(r"ANSWER:\\s*\\d+", name="has_format"))
        reg.add(LengthBandEvaluator(0, 500, name="brief"))
        reg.add(TrajectoryShapeEvaluator(min_tool_calls=1, name="used_tools"))
        scores = reg.run(answer, task=t, trajectory=traj)
        # -> {"has_format": EvalScore(...), "brief": ..., "used_tools": ...}
    """

    def __init__(self):
        self._evals: list[Evaluator] = []

    def add(self, evaluator: Evaluator) -> "EvaluatorRegistry":
        self._evals.append(evaluator)
        return self

    def run(self, final_answer: str, task: Any = None, trajectory=None) -> dict[str, EvalScore]:
        return {e.name: e.score(final_answer, task=task, trajectory=trajectory) for e in self._evals}

    def __len__(self) -> int:
        return len(self._evals)
