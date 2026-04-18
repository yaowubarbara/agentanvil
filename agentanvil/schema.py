"""
v0.1 trajectory schema + compliance validator.

Kept deliberately lightweight — no jsonschema dependency; we encode the MUST
rules from docs/TRAJECTORY_PROTOCOL.md directly. Adding jsonschema later is a
non-breaking change if anyone needs cross-language validation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .trajectory import EventKind, Trajectory

PROTOCOL_VERSION = "0.1"

_VALID_KINDS = {k.value for k in EventKind}


@dataclass
class ValidationIssue:
    rule: str
    detail: str
    step: int | None = None

    def __str__(self) -> str:
        where = f" @step{self.step}" if self.step is not None else ""
        return f"[{self.rule}]{where} {self.detail}"


def validate(traj: Trajectory | dict) -> list[ValidationIssue]:
    """Return a list of issues; empty list means compliant."""
    data = traj.to_json() if isinstance(traj, Trajectory) else traj
    issues: list[ValidationIssue] = []

    for req in ("trajectory_id", "task_id", "scaffold", "started_at", "events"):
        if req not in data:
            issues.append(ValidationIssue("top-level", f"missing required field '{req}'"))
    events = data.get("events", [])

    if not events:
        issues.append(ValidationIssue("MUST-1", "events is empty"))
        return issues

    if events[0].get("kind") != EventKind.OBSERVATION.value:
        issues.append(
            ValidationIssue("MUST-2", f"first event must be observation, got {events[0].get('kind')}", step=0)
        )

    non_reward = [e for e in events if e.get("kind") != EventKind.REWARD.value]
    if non_reward:
        last_kind = non_reward[-1].get("kind")
        if last_kind not in (EventKind.FINAL_ANSWER.value, EventKind.ERROR.value):
            issues.append(
                ValidationIssue(
                    "MUST-3",
                    f"last non-reward event must be final_answer or error, got {last_kind}",
                    step=non_reward[-1].get("step"),
                )
            )

    finals = [e for e in events if e.get("kind") == EventKind.FINAL_ANSWER.value]
    errors = [e for e in events if e.get("kind") == EventKind.ERROR.value]
    if len(finals) > 1:
        issues.append(ValidationIssue("MUST-4", f"{len(finals)} final_answer events (max 1)"))
    if len(errors) > 1:
        issues.append(ValidationIssue("MUST-4", f"{len(errors)} error events (max 1)"))
    if finals and errors:
        issues.append(ValidationIssue("MUST-4", "trajectory has both final_answer and error"))

    for i, e in enumerate(events):
        if e.get("step") != i:
            issues.append(
                ValidationIssue("MUST-5", f"step index mismatch: expected {i}, got {e.get('step')}", step=i)
            )
        if e.get("kind") not in _VALID_KINDS:
            issues.append(ValidationIssue("MUST-*", f"unknown kind {e.get('kind')!r}", step=i))

    prev_ts = -float("inf")
    for i, e in enumerate(events):
        ts = e.get("ts", 0)
        if ts < prev_ts:
            issues.append(
                ValidationIssue("MUST-6", f"timestamp decreases: {ts} < {prev_ts}", step=i)
            )
        prev_ts = ts

    try:
        json.loads(json.dumps(data))
    except (TypeError, ValueError) as exc:
        issues.append(ValidationIssue("MUST-7", f"trajectory not JSON-round-trippable: {exc}"))

    issues.extend(_validate_tool_pairing(events))

    return issues


def _validate_tool_pairing(events: list[dict]) -> list[ValidationIssue]:
    """MUST-8: every tool_result pairs with a preceding unmatched tool_call."""
    issues: list[ValidationIssue] = []
    open_calls: list[dict] = []
    for i, e in enumerate(events):
        kind = e.get("kind")
        if kind == EventKind.TOOL_CALL.value:
            open_calls.append(e)
        elif kind == EventKind.TOOL_RESULT.value:
            content = e.get("content") or {}
            call_id = content.get("call_id") if isinstance(content, dict) else None
            if call_id:
                match = next(
                    (c for c in open_calls if (c.get("content") or {}).get("call_id") == call_id),
                    None,
                )
                if match is None:
                    issues.append(
                        ValidationIssue(
                            "MUST-8",
                            f"tool_result with call_id={call_id!r} has no matching tool_call",
                            step=i,
                        )
                    )
                else:
                    open_calls.remove(match)
            else:
                if not open_calls:
                    issues.append(
                        ValidationIssue(
                            "MUST-8", "tool_result has no preceding unmatched tool_call", step=i
                        )
                    )
                else:
                    open_calls.pop()
    return issues


def is_compliant(traj: Trajectory | dict) -> bool:
    return not validate(traj)
