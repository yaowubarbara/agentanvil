"""
Unit tests for the Phase 2+ verifiers (GSM8K / HumanEval / SWE-bench Lite).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentanvil.verifier.gsm8k import GSM8KTask, GSM8KVerifier
from agentanvil.verifier.humaneval import HumanEvalTask, HumanEvalVerifier
from agentanvil.verifier.swe_bench_lite import SWEBenchLiteTask, SWEBenchLiteVerifier


# ── GSM8K ─────────────────────────────────────────────────────────────

def test_gsm8k_hash_marker_correct():
    v = GSM8KVerifier()
    t = GSM8KTask(task_id="g1", question="Q", gold_answer="... #### 42")
    r = v.verify("Reasoning...\n#### 42", t)
    assert r.correct and r.parsed == 42.0 and r.gold == 42.0


def test_gsm8k_hash_marker_wrong():
    v = GSM8KVerifier()
    t = GSM8KTask(task_id="g1", question="Q", gold_answer="#### 42")
    r = v.verify("#### 41", t)
    assert not r.correct and r.reward == 0.0


def test_gsm8k_last_int_fallback():
    v = GSM8KVerifier(strict=False)
    t = GSM8KTask(task_id="g1", question="Q", gold_answer="#### 5")
    r = v.verify("I think the answer is 5.", t)
    assert r.correct and r.parsed == 5.0
    assert r.meta["marker_used"] == "last_int"


def test_gsm8k_strict_no_marker_fails():
    v = GSM8KVerifier(strict=True)
    t = GSM8KTask(task_id="g1", question="Q", gold_answer="#### 5")
    r = v.verify("The answer is 5", t)
    assert not r.correct and r.meta["parse_failed"]


def test_gsm8k_comma_formatted_number():
    v = GSM8KVerifier()
    t = GSM8KTask(task_id="g1", question="Q", gold_answer="#### 1,234")
    r = v.verify("#### 1,234", t)
    assert r.correct and r.parsed == 1234.0


# ── HumanEval ────────────────────────────────────────────────────────

def test_humaneval_passing_solution():
    task = HumanEvalTask(
        task_id="HumanEval/fake-0",
        prompt="def add_one(x):\n    '''Return x + 1.'''\n",
        test_code="def check(c):\n    assert c(1) == 2\n    assert c(-5) == -4\n",
        entry_point="add_one",
    )
    v = HumanEvalVerifier(timeout_seconds=5)
    r = v.verify("```python\ndef add_one(x):\n    return x + 1\n```", task)
    assert r.correct, f"expected pass, got meta={r.meta}"
    assert r.reward == 1.0


def test_humaneval_failing_solution():
    task = HumanEvalTask(
        task_id="HumanEval/fake-1",
        prompt="def add_one(x):\n    pass\n",
        test_code="def check(c):\n    assert c(1) == 2\n",
        entry_point="add_one",
    )
    v = HumanEvalVerifier(timeout_seconds=5)
    r = v.verify("```python\ndef add_one(x):\n    return x + 2\n```", task)
    assert not r.correct


def test_humaneval_parse_fail_on_no_fence():
    task = HumanEvalTask(
        task_id="HumanEval/fake-2",
        prompt="def f(): pass",
        test_code="def check(c): pass",
        entry_point="f",
    )
    v = HumanEvalVerifier()
    r = v.verify("I think the solution is to return 1.", task)
    assert not r.correct and r.meta["parse_failed"]


# ── SWE-bench Lite ───────────────────────────────────────────────────

GOLD_PATCH = """diff --git a/src/foo.py b/src/foo.py
index 111..222 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,3 @@
-def bar():
-    return None
+def bar():
+    return 42
"""

def test_swe_bench_lite_exact_match_binary():
    v = SWEBenchLiteVerifier(binary=True)
    task = SWEBenchLiteTask(
        task_id="swe/0", repo="x/y", base_commit="abc",
        problem_statement="fix bar", gold_patch=GOLD_PATCH,
    )
    r = v.verify(f"Here's the fix:\n```diff\n{GOLD_PATCH}\n```", task)
    assert r.correct and r.reward == 1.0


def test_swe_bench_lite_overlap_scalar():
    v = SWEBenchLiteVerifier(binary=False)
    task = SWEBenchLiteTask(
        task_id="swe/0", repo="x/y", base_commit="abc",
        problem_statement="fix bar", gold_patch=GOLD_PATCH,
    )
    # Patch touches same file, slightly different
    r = v.verify(
        "```diff\ndiff --git a/src/foo.py b/src/foo.py\n@@ -1,2 +1,2 @@\n-x\n+y\n```",
        task,
    )
    assert 0.0 < r.reward < 1.0
    assert r.meta["file_jaccard"] == 1.0


def test_swe_bench_lite_parse_fail():
    v = SWEBenchLiteVerifier()
    task = SWEBenchLiteTask(
        task_id="swe/0", repo="x/y", base_commit="abc",
        problem_statement="fix", gold_patch=GOLD_PATCH,
    )
    r = v.verify("I would change bar to return 42", task)
    assert not r.correct and r.meta["parse_failed"]


def test_swe_bench_lite_different_files_zero_jaccard():
    v = SWEBenchLiteVerifier(binary=False)
    task = SWEBenchLiteTask(
        task_id="swe/0", repo="x/y", base_commit="abc",
        problem_statement="fix", gold_patch=GOLD_PATCH,
    )
    wrong_file = "diff --git a/other/zzz.py b/other/zzz.py\n@@ -1 +1 @@\n-a\n+b"
    r = v.verify(f"```diff\n{wrong_file}\n```", task)
    assert r.meta["file_jaccard"] == 0.0


if __name__ == "__main__":
    tests = [fn for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn)]
    passed = 0
    failed = []
    for fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            failed.append((fn.__name__, str(e)))
            print(f"  ✗ {fn.__name__}: {e}")
        except Exception as e:
            failed.append((fn.__name__, f"{type(e).__name__}: {e}"))
            print(f"  ✗ {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    if failed:
        sys.exit(1)
