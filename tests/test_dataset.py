"""
Tests for Dataset and task pack loading.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentanvil.dataset import Dataset, PackMeta


def test_list_builtin_packs():
    packs = Dataset.list_packs()
    assert "gsm8k-mini" in packs
    assert "humaneval-mini" in packs
    assert "jordan-count-mini" in packs
    assert "swe-bench-micro" in packs
    assert len(packs) >= 4


def test_load_gsm8k_mini():
    ds = Dataset.from_pack("gsm8k-mini")
    assert ds.meta.name == "gsm8k-mini"
    assert len(ds) == 12
    assert ds.tasks[0].task_id == "gsm8k-mini/001"
    assert "#### 6" in ds.tasks[0].gold_answer


def test_load_humaneval_mini():
    ds = Dataset.from_pack("humaneval-mini")
    assert ds.meta.name == "humaneval-mini"
    assert len(ds) == 8
    # entry_point should be set on every task
    for t in ds.tasks:
        assert t.entry_point


def test_load_jordan_count_mini():
    ds = Dataset.from_pack("jordan-count-mini")
    assert len(ds) == 6
    for t in ds.tasks:
        assert isinstance(t.gold_count, int)


def test_load_swe_bench_micro():
    ds = Dataset.from_pack("swe-bench-micro")
    assert len(ds) == 4
    for t in ds.tasks:
        assert "diff --git" in t.gold_patch


def test_dataset_sample_and_take():
    ds = Dataset.from_pack("gsm8k-mini")
    sub = ds.take(3)
    assert len(sub) == 3
    sampled = ds.sample(5, seed=42)
    assert len(sampled) == 5


def test_dataset_iteration_yields_task_plus_verifier():
    ds = Dataset.from_pack("gsm8k-mini")
    count = 0
    for task, verifier in ds:
        count += 1
        assert verifier is not None
        assert hasattr(verifier, "verify")
        assert task.task_id.startswith("gsm8k-mini/")
    assert count == 12


def test_dataset_verifier_end_to_end_gsm8k():
    """Smoke: run the full verifier on the first task's gold answer — must be correct."""
    ds = Dataset.from_pack("gsm8k-mini")
    task = ds.tasks[0]
    verifier = ds.verifier()
    r = verifier.verify(task.gold_answer, task)
    assert r.correct, f"verifier failed on gold: parsed={r.parsed} gold={r.gold}"


def test_dataset_filter():
    ds = Dataset.from_pack("jordan-count-mini")
    hard = ds.filter(lambda t: t.gold_count >= 3)
    assert len(hard) < len(ds)
    assert all(t.gold_count >= 3 for t in hard.tasks)


def test_missing_pack_raises():
    try:
        Dataset.from_pack("nonexistent-pack-xyz")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")


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
