"""
CLI smoke tests.

Runs the argparse parser end-to-end on each subcommand and checks basic
shape of the output. Does NOT call live LLM APIs — `eval run` is tested
only for argument parsing via `--limit 0`.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentanvil.cli import main


def test_packs_list():
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(["packs", "list"])
    assert code == 0
    out = buf.getvalue()
    assert "gsm8k-mini" in out
    assert "humaneval-mini" in out


def test_packs_show():
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(["packs", "show", "gsm8k-mini", "--head", "3"])
    assert code == 0
    out = buf.getvalue()
    assert "gsm8k-mini/001" in out
    assert "Tasks:" in out
    import re
    m = re.search(r"Tasks:\s+(\d+)", out)
    assert m and int(m.group(1)) >= 12


def test_traces_tail_on_known_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        json.dump({
            "trajectory_id": "abc", "task_id": "t1", "scaffold": "test",
            "events": [{"kind": "observation", "content": {}, "step": 0, "ts": 0, "meta": {}},
                       {"kind": "final_answer", "content": "x", "step": 1, "ts": 1, "meta": {}}],
            "verify": {"correct": True, "reward": 1.0},
        }, f)
        f.write("\n")
        path = f.name
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(["traces", "tail", "--path", path, "-n", "5"])
    assert code == 0
    out = buf.getvalue()
    assert "test" in out and "t1" in out


def test_traces_stats_aggregates():
    rows = [
        {"trajectory_id": "a", "task_id": "t1", "scaffold": "A",
         "events": [{"kind": "observation", "content": {}, "step": 0, "ts": 0, "meta": {}},
                    {"kind": "final_answer", "content": "x", "step": 1, "ts": 1, "meta": {}}],
         "verify": {"correct": True, "reward": 1.0}},
        {"trajectory_id": "b", "task_id": "t2", "scaffold": "A",
         "events": [{"kind": "observation", "content": {}, "step": 0, "ts": 0, "meta": {}},
                    {"kind": "final_answer", "content": "x", "step": 1, "ts": 1, "meta": {}}],
         "verify": {"correct": False, "reward": 0.0}},
        {"trajectory_id": "c", "task_id": "t1", "scaffold": "B",
         "events": [{"kind": "observation", "content": {}, "step": 0, "ts": 0, "meta": {}},
                    {"kind": "final_answer", "content": "x", "step": 1, "ts": 1, "meta": {}}],
         "verify": {"correct": True, "reward": 1.0}},
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        path = f.name
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(["traces", "stats", "--path", path])
    assert code == 0
    out = buf.getvalue()
    assert "Total trajectories: 3" in out
    assert "A" in out and "B" in out
    assert "50.0%" in out
    assert "100.0%" in out


def test_validate_compliant_file():
    good = {
        "trajectory_id": "abc", "task_id": "t1", "scaffold": "test",
        "started_at": 0, "finished_at": 1, "meta": {},
        "events": [
            {"kind": "observation", "content": {"text": "hi"}, "step": 0, "ts": 0, "meta": {}},
            {"kind": "final_answer", "content": "x", "step": 1, "ts": 1, "meta": {}},
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(good) + "\n")
        path = f.name
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(["validate", path])
    assert code == 0
    assert "1/1 compliant" in buf.getvalue()


def test_validate_noncompliant_file():
    bad = {
        "trajectory_id": "abc", "task_id": "t1", "scaffold": "test",
        "started_at": 0, "finished_at": 1, "meta": {},
        "events": [
            {"kind": "thought", "content": {}, "step": 0, "ts": 0, "meta": {}},  # MUST-2 fail
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(bad) + "\n")
        path = f.name
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(["validate", path])
    assert code == 2
    out = buf.getvalue()
    assert "MUST-" in out


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
