"""
Dataset management.

A Dataset is an iterable of AnvilTask-typed items plus metadata about the
verifier that should be used. The same Dataset can back:
  - A single-scaffold eval run (rolling through every task)
  - A cross-scaffold comparison (same tasks, multiple agents)
  - An RL training epoch (shuffle, batch, stream to trainer)

On-disk layout — each "pack" is a directory under `agentanvil/packs/` with:
    pack.yaml          # metadata (name, verifier, version, license, source)
    tasks.jsonl        # one task per line; fields interpreted by verifier

Packs are deliberately JSONL-on-disk (not a Python module) so that:
  1. Non-Python tools (CLI, CI, external trainers) can consume them
  2. Swapping packs is file-level, not code-level
  3. HuggingFace datasets can be converted to this shape with a one-shot
     script — not integrated as a run-time dep
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import importlib
import sys


@dataclass
class PackMeta:
    name: str
    verifier: str          # dotted path: "agentanvil.verifier.gsm8k.GSM8KVerifier"
    task_class: str        # dotted path: "agentanvil.verifier.gsm8k.GSM8KTask"
    version: str = "0.1.0"
    license: str = "unspecified"
    source: str = "unspecified"
    description: str = ""


@dataclass
class Dataset:
    """A collection of verifiable tasks for one suite.

    Iteration yields (task_instance, verifier_instance) pairs. The verifier
    is shared across all tasks in the Dataset — but a training loop that
    needs per-task verifier state can clone it.
    """

    meta: PackMeta
    tasks: list = field(default_factory=list)
    _verifier_cache: Any = None

    def __len__(self) -> int:
        return len(self.tasks)

    def __iter__(self) -> Iterator[tuple]:
        verifier = self.verifier()
        for t in self.tasks:
            yield t, verifier

    def sample(self, n: int, seed: int = 0) -> "Dataset":
        rng = random.Random(seed)
        idx = list(range(len(self.tasks)))
        rng.shuffle(idx)
        return Dataset(meta=self.meta, tasks=[self.tasks[i] for i in idx[:n]])

    def filter(self, predicate: Callable[[Any], bool]) -> "Dataset":
        return Dataset(meta=self.meta, tasks=[t for t in self.tasks if predicate(t)])

    def take(self, n: int) -> "Dataset":
        return Dataset(meta=self.meta, tasks=self.tasks[:n])

    def verifier(self):
        if self._verifier_cache is None:
            self._verifier_cache = _import_dotted(self.meta.verifier)()
        return self._verifier_cache

    @classmethod
    def from_pack(cls, path: str | Path) -> "Dataset":
        pack_dir = Path(path)
        if not pack_dir.is_dir():
            # Treat as a pack name; look under builtin packs/
            pack_dir = Path(__file__).parent / "packs" / str(path)
        if not pack_dir.is_dir():
            raise FileNotFoundError(f"pack directory not found: {path}")
        meta_path = pack_dir / "pack.yaml"
        tasks_path = pack_dir / "tasks.jsonl"
        if not meta_path.exists() or not tasks_path.exists():
            raise FileNotFoundError(f"pack at {pack_dir} is missing pack.yaml or tasks.jsonl")

        meta_raw = _parse_simple_yaml(meta_path.read_text())
        meta = PackMeta(**meta_raw)
        task_cls = _import_dotted(meta.task_class)

        tasks = []
        with tasks_path.open() as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    tasks.append(task_cls(**row))
                except Exception as e:
                    raise ValueError(f"{pack_dir}/tasks.jsonl line {i+1}: {e}") from e
        return cls(meta=meta, tasks=tasks)

    @classmethod
    def list_packs(cls) -> list[str]:
        packs_dir = Path(__file__).parent / "packs"
        if not packs_dir.is_dir():
            return []
        return sorted(
            p.name for p in packs_dir.iterdir()
            if p.is_dir() and (p / "pack.yaml").exists()
        )


def _import_dotted(dotted: str):
    mod_name, _, cls_name = dotted.rpartition(".")
    if not mod_name:
        raise ValueError(f"bad dotted path: {dotted!r}")
    try:
        module = importlib.import_module(mod_name)
    except ImportError:
        if mod_name in sys.modules:
            module = sys.modules[mod_name]
        else:
            raise
    return getattr(module, cls_name)


def _parse_simple_yaml(text: str) -> dict:
    """Minimal YAML parser for flat key: value files. Avoids pyyaml dep.

    Supports:
      key: "string value"
      key: string value
      # comments
      blank lines
    Does NOT support nesting, lists, anchors, multi-line strings, etc.
    """
    out: dict = {}
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        out[key] = val
    return out
