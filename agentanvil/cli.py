"""
AgentAnvil CLI — `aa` command.

Subcommands:
  aa packs list                     # show available task packs
  aa packs show <name>              # print pack meta + sample tasks
  aa eval run <pack> [--adapter ..] [--model ..] [--limit N] [--out ..]
                                    # run an adapter across a pack, write traces
  aa traces tail [--path ..]        # tail the latest trace JSONL
  aa traces stats [--path ..]       # aggregate accuracy + counts by scaffold
  aa validate <traces.jsonl>        # run protocol conformance validator

Design notes:
  - Uses argparse (stdlib) — no external CLI framework dep.
  - All commands work with the local JSONL sink; no external services required.
  - Evaluators are opt-in: `aa eval run ... --adapter minimal` requires the
    anthropic/openai SDK installed; other adapters degrade gracefully with a
    pip-hint error message.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional


def _cmd_packs_list(args) -> int:
    from .dataset import Dataset

    packs = Dataset.list_packs()
    if not packs:
        print("(no packs found under agentanvil/packs/)")
        return 1
    print("Available packs:")
    for p in packs:
        try:
            ds = Dataset.from_pack(p)
            print(f"  {p:<24} n={len(ds):<4} verifier={ds.meta.verifier.rsplit('.', 1)[-1]}")
        except Exception as e:
            print(f"  {p:<24} (failed to load: {e})")
    return 0


def _cmd_packs_show(args) -> int:
    from .dataset import Dataset

    ds = Dataset.from_pack(args.name)
    print(f"Pack: {ds.meta.name}")
    print(f"Version: {ds.meta.version}")
    print(f"Verifier: {ds.meta.verifier}")
    print(f"TaskClass: {ds.meta.task_class}")
    print(f"License: {ds.meta.license}")
    print(f"Source: {ds.meta.source}")
    print(f"Description: {ds.meta.description}")
    print(f"Tasks: {len(ds)}")
    n_show = min(args.head, len(ds))
    print(f"\nFirst {n_show} tasks:")
    for t in ds.tasks[:n_show]:
        print(f"  - {t.task_id}")
    return 0


def _cmd_eval_run(args) -> int:
    from .dataset import Dataset
    from .runner import run_one
    from .trace.local import LocalJsonlSink

    ds = Dataset.from_pack(args.pack)
    if args.limit:
        ds = ds.take(args.limit)

    adapter = _build_adapter(args.adapter, args.model, args.provider)
    verifier = ds.verifier()
    sinks = [LocalJsonlSink(args.out)]

    total = len(ds)
    correct = 0
    print(f"Evaluating {adapter.scaffold_name} on {ds.meta.name} (n={total}) → {args.out}")
    for i, t in enumerate(ds.tasks, 1):
        traj, result = run_one(adapter, t, verifier, sinks)
        if result.correct:
            correct += 1
        marker = "✓" if result.correct else "✗"
        print(f"  [{i}/{total}] {marker} {t.task_id} parsed={result.parsed} gold={result.gold} r={result.reward}")
    print(f"\nAccuracy: {correct}/{total} = {correct/total:.1%}" if total else "(empty)")
    return 0 if correct > 0 else 1


def _cmd_traces_tail(args) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"(no file at {path})")
        return 1
    lines = path.read_text().strip().split("\n")
    if not lines or not lines[0]:
        print("(empty)")
        return 0
    n = min(args.n, len(lines))
    for line in lines[-n:]:
        try:
            rec = json.loads(line)
            scaff = rec.get("scaffold", "?")
            task = rec.get("task_id", "?")
            v = rec.get("verify") or {}
            ok = v.get("correct")
            r = v.get("reward", "?")
            nev = len(rec.get("events", []))
            print(f"  {scaff:<20} {task:<24} events={nev:<3} r={r} {'✓' if ok else '✗' if ok is False else '?'}")
        except json.JSONDecodeError:
            print(f"  (malformed line)")
    return 0


def _cmd_traces_stats(args) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"(no file at {path})")
        return 1
    from collections import defaultdict

    by_scaffold: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "correct": 0, "events": 0})
    by_task: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "correct": 0})
    total = 0
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += 1
            sc = rec.get("scaffold", "?")
            tk = rec.get("task_id", "?")
            v = rec.get("verify") or {}
            ok = v.get("correct")
            nev = len(rec.get("events", []))
            by_scaffold[sc]["n"] += 1
            by_scaffold[sc]["events"] += nev
            by_task[tk]["n"] += 1
            if ok:
                by_scaffold[sc]["correct"] += 1
                by_task[tk]["correct"] += 1
    print(f"Total trajectories: {total}\n")
    print(f"{'Scaffold':<22} {'N':>5} {'Correct':>8} {'Acc':>7} {'AvgEvents':>10}")
    print("-" * 60)
    for sc, s in sorted(by_scaffold.items(), key=lambda kv: -kv[1]['n']):
        acc = s["correct"] / s["n"] if s["n"] else 0
        avg = s["events"] / s["n"] if s["n"] else 0
        print(f"{sc:<22} {s['n']:>5} {s['correct']:>8} {acc:>6.1%} {avg:>10.1f}")
    return 0


def _cmd_validate(args) -> int:
    from .schema import validate

    path = Path(args.path)
    if not path.exists():
        print(f"(no file at {path})")
        return 1
    total = 0
    bad = 0
    with path.open() as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  line {i}: not JSON ({e})")
                bad += 1
                continue
            issues = validate(rec)
            if issues:
                bad += 1
                print(f"  line {i} ({rec.get('trajectory_id', '?')[:8]}): {len(issues)} issue(s)")
                for iss in issues:
                    print(f"      {iss}")
    print(f"\n{total - bad}/{total} compliant ({total} total, {bad} invalid)")
    return 0 if bad == 0 else 2


def _build_adapter(kind: str, model: Optional[str], provider: Optional[str]) -> Any:
    if kind == "minimal":
        from .adapter.minimal import MinimalAdapter
        return MinimalAdapter(provider=provider or "anthropic", model=model)
    if kind == "claude-code":
        from .adapter.claude_code import ClaudeCodeAdapter
        return ClaudeCodeAdapter(model=model)
    raise SystemExit(
        f"Unknown / unimplemented adapter kind: {kind}. Available: minimal, claude-code. "
        "Other adapters (openai-agents, langchain, openhands, autogen, crewai, langgraph, "
        "llamaindex) require a pre-configured scaffold instance; use the Python API."
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aa", description="AgentAnvil command-line interface")
    sub = p.add_subparsers(dest="cmd", required=True)

    packs = sub.add_parser("packs", help="manage task packs")
    packs_sub = packs.add_subparsers(dest="packs_cmd", required=True)
    packs_sub.add_parser("list", help="list available packs").set_defaults(func=_cmd_packs_list)
    show = packs_sub.add_parser("show", help="show pack metadata + sample tasks")
    show.add_argument("name")
    show.add_argument("--head", type=int, default=5)
    show.set_defaults(func=_cmd_packs_show)

    ev = sub.add_parser("eval", help="run evaluations")
    ev_sub = ev.add_subparsers(dest="eval_cmd", required=True)
    run = ev_sub.add_parser("run", help="run an adapter across a pack")
    run.add_argument("pack")
    run.add_argument("--adapter", default="minimal")
    run.add_argument("--model", default=None)
    run.add_argument("--provider", default=None)
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--out", default="traces/traces.jsonl")
    run.set_defaults(func=_cmd_eval_run)

    tr = sub.add_parser("traces", help="inspect trajectories")
    tr_sub = tr.add_subparsers(dest="traces_cmd", required=True)
    tail = tr_sub.add_parser("tail", help="show recent trajectories")
    tail.add_argument("--path", default="traces/traces.jsonl")
    tail.add_argument("-n", type=int, default=10)
    tail.set_defaults(func=_cmd_traces_tail)
    stats = tr_sub.add_parser("stats", help="aggregate accuracy by scaffold")
    stats.add_argument("--path", default="traces/traces.jsonl")
    stats.set_defaults(func=_cmd_traces_stats)

    v = sub.add_parser("validate", help="check protocol conformance of a JSONL file")
    v.add_argument("path")
    v.set_defaults(func=_cmd_validate)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
