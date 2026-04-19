"""
Tests for the evaluator framework.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentanvil.evaluator import (
    ContainsKeywordsEvaluator,
    EvaluatorRegistry,
    LLMJudgeEvaluator,
    LengthBandEvaluator,
    NoForbiddenWordsEvaluator,
    RegexEvaluator,
    RubricCriterion,
    RubricEvaluator,
    TrajectoryShapeEvaluator,
)
from agentanvil.trajectory import EventKind, Trajectory


# ── Programmatic ────────────────────────────────────────────────────

def test_contains_keywords_all():
    e = ContainsKeywordsEvaluator(["fruit", "apple"])
    s = e.score("I like fruit, especially apple.")
    assert s.value == 1.0 and s.label == "all"


def test_contains_keywords_partial():
    e = ContainsKeywordsEvaluator(["fruit", "apple", "banana"])
    s = e.score("I like fruit, especially apple.")
    assert s.value == 2 / 3


def test_contains_keywords_none():
    e = ContainsKeywordsEvaluator(["xenon"])
    s = e.score("nothing relevant")
    assert s.value == 0.0 and s.label == "none"


def test_regex_match():
    e = RegexEvaluator(r"ANSWER:\s*(\d+)", name="ans_fmt")
    s = e.score("... ANSWER: 42")
    assert s.value == 1.0 and s.meta["groups"] == ["42"]


def test_regex_no_match():
    e = RegexEvaluator(r"ANSWER:\s*\d+")
    s = e.score("I think it's forty-two.")
    assert s.value == 0.0 and s.label == "no-match"


def test_length_band_in():
    e = LengthBandEvaluator(5, 20)
    s = e.score("short.")
    assert s.value == 1.0 and s.label == "in_band"


def test_length_band_too_short():
    e = LengthBandEvaluator(10, 20)
    s = e.score("hi")
    assert s.value == 0.0 and s.label == "too_short"


def test_length_band_too_long():
    e = LengthBandEvaluator(1, 5)
    s = e.score("this is definitely longer than five characters")
    assert s.label == "too_long"


def test_no_forbidden_clean():
    e = NoForbiddenWordsEvaluator(["hack", "exploit"])
    s = e.score("A thoughtful essay.")
    assert s.value == 1.0


def test_no_forbidden_violation():
    e = NoForbiddenWordsEvaluator(["hack"])
    s = e.score("Here's a hack for you.")
    assert s.value == 0.0 and "hack" in s.meta["hits"]


# ── Trajectory-based ────────────────────────────────────────────────

def _traj_with(kinds_and_content):
    t = Trajectory(task_id="t", scaffold="s")
    for k, c in kinds_and_content:
        t.emit(k, c)
    t.finish()
    return t


def test_trajectory_shape_enough_tools():
    traj = _traj_with([
        (EventKind.OBSERVATION, {}),
        (EventKind.TOOL_CALL, {"name": "x", "arguments": {}}),
        (EventKind.TOOL_RESULT, {"output": "y"}),
        (EventKind.TOOL_CALL, {"name": "x", "arguments": {}}),
        (EventKind.TOOL_RESULT, {"output": "z"}),
        (EventKind.FINAL_ANSWER, "ok"),
    ])
    e = TrajectoryShapeEvaluator(min_tool_calls=1, max_tool_calls=5, require_kind="tool_result")
    s = e.score("ok", trajectory=traj)
    assert s.value == 1.0 and s.label == "all_pass"


def test_trajectory_shape_too_many_tools():
    traj = _traj_with([
        (EventKind.OBSERVATION, {}),
        (EventKind.TOOL_CALL, {"name": "x", "arguments": {}}),
        (EventKind.TOOL_RESULT, {"output": "y"}),
        (EventKind.TOOL_CALL, {"name": "x", "arguments": {}}),
        (EventKind.TOOL_RESULT, {"output": "y"}),
        (EventKind.TOOL_CALL, {"name": "x", "arguments": {}}),
        (EventKind.TOOL_RESULT, {"output": "y"}),
        (EventKind.FINAL_ANSWER, "ok"),
    ])
    e = TrajectoryShapeEvaluator(min_tool_calls=0, max_tool_calls=2)
    s = e.score("ok", trajectory=traj)
    assert s.meta["n_tool_calls"] == 3
    assert s.value < 1.0


def test_trajectory_shape_no_trajectory():
    e = TrajectoryShapeEvaluator(min_tool_calls=1)
    s = e.score("ok", trajectory=None)
    assert s.value == 0.0 and s.label == "no_trajectory"


# ── Rubric ───────────────────────────────────────────────────────────

def test_rubric_weighted_sum():
    rubric = RubricEvaluator(
        "quality",
        [
            RubricCriterion("fmt", 0.6, RegexEvaluator(r"ANSWER:\s*\d+")),
            RubricCriterion("brief", 0.4, LengthBandEvaluator(0, 100)),
        ],
    )
    good = rubric.score("ANSWER: 42")
    assert good.value == 1.0
    # Only brief passes
    partial = rubric.score("Short.")
    assert abs(partial.value - 0.4) < 1e-9


def test_rubric_weights_normalize():
    rubric = RubricEvaluator(
        "q",
        [
            RubricCriterion("a", 2.0, RegexEvaluator(r"x")),  # fails
            RubricCriterion("b", 3.0, RegexEvaluator(r"y")),  # passes
        ],
    )
    s = rubric.score("y only")
    assert abs(s.value - 3 / 5) < 1e-9


def test_rubric_zero_weight_rejected():
    try:
        RubricEvaluator("bad", [])
        raise AssertionError("should raise on empty rubric")
    except ValueError:
        pass


# ── LLM judge (stubbed — no real API calls) ─────────────────────────

def test_llm_judge_parse_success():
    def fake_llm(_prompt):
        return "SCORE: 5\nREASON: Correctly followed the ANSWER format and solved the problem."

    judge = LLMJudgeEvaluator(criterion="correctness", call_fn=fake_llm)
    s = judge.score("ANSWER: 42", task=None)
    assert s.value == 1.0
    assert s.label == "5/5"
    assert "Correctly" in s.reasoning


def test_llm_judge_parse_mid_score():
    def fake_llm(_p):
        return "SCORE: 3\nREASON: partial credit"

    judge = LLMJudgeEvaluator(criterion="quality", call_fn=fake_llm)
    s = judge.score("answer")
    assert s.value == 0.5
    assert s.label == "3/5"


def test_llm_judge_parse_failure():
    def fake_llm(_p):
        return "I think this is a pretty good answer overall."

    judge = LLMJudgeEvaluator(criterion="c", call_fn=fake_llm)
    s = judge.score("answer")
    assert s.value == 0.0
    assert s.label == "parse_fail"


def test_llm_judge_handles_task_with_gold():
    captured = {}

    def fake_llm(prompt):
        captured["prompt"] = prompt
        return "SCORE: 4\nREASON: x"

    class _Task:
        task_id = "t"
        question = "2+2?"
        gold_answer = "4"

    judge = LLMJudgeEvaluator(criterion="c", call_fn=fake_llm)
    judge.score("ANSWER: 4", task=_Task())
    assert "2+2" in captured["prompt"]
    assert "4" in captured["prompt"]


# ── Registry ─────────────────────────────────────────────────────────

def test_registry_runs_all():
    reg = EvaluatorRegistry()
    reg.add(RegexEvaluator(r"ANSWER:\s*\d+", name="fmt"))
    reg.add(LengthBandEvaluator(0, 100, name="brief"))
    reg.add(NoForbiddenWordsEvaluator(["hack"], name="safe"))
    scores = reg.run("ANSWER: 42")
    assert len(scores) == 3
    assert set(scores) == {"fmt", "brief", "safe"}
    assert scores["fmt"].value == 1.0
    assert scores["safe"].value == 1.0


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn)]
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {name}")
        except AssertionError as e:
            failed.append((name, str(e)))
            print(f"  ✗ {name}: {e}")
        except Exception as e:
            failed.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    if failed:
        sys.exit(1)
