"""
Unified Trajectory Protocol.

A trajectory is a flat sequence of typed events. Every adapter (OpenAI Agents SDK,
Claude Code, OpenHands, LangChain, custom) maps its native trace to this shape.

Design goals:
- Replayable: UI can step through without knowing the scaffold.
- Scorable: verifiers see a clean final_answer, independent of scaffold.
- RL-ready: reward events attach at trajectory end; can be redistributed later
  by credit assignment strategies living outside this protocol.
- Narrow: we deliberately do NOT try to faithfully round-trip every scaffold's
  internal state. If a scaffold has unique richness, store it in event.meta.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class EventKind(str, Enum):
    OBSERVATION = "observation"
    THOUGHT = "thought"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL_ANSWER = "final_answer"
    REWARD = "reward"
    ERROR = "error"


@dataclass
class Event:
    kind: EventKind
    content: Any
    step: int
    ts: float = field(default_factory=time.time)
    meta: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d


@dataclass
class Trajectory:
    task_id: str
    scaffold: str
    events: list[Event] = field(default_factory=list)
    trajectory_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    meta: dict = field(default_factory=dict)

    def append(self, event: Event) -> None:
        self.events.append(event)

    def emit(self, kind: EventKind, content: Any, **meta: Any) -> Event:
        e = Event(kind=kind, content=content, step=len(self.events), meta=dict(meta))
        self.append(e)
        return e

    def finish(self) -> None:
        self.finished_at = time.time()

    def final_answer(self) -> Optional[str]:
        for e in reversed(self.events):
            if e.kind == EventKind.FINAL_ANSWER:
                return str(e.content) if e.content is not None else None
        return None

    def to_json(self) -> dict:
        return {
            "trajectory_id": self.trajectory_id,
            "task_id": self.task_id,
            "scaffold": self.scaffold,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "meta": self.meta,
            "events": [e.to_json() for e in self.events],
        }
