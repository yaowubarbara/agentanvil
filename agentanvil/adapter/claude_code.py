"""
Claude Code adapter — headless CLI integration.

This is the canonical "Claude Code 二次开发" path in production: invoke
  claude -p <prompt> --output-format stream-json --verbose
parse the JSONL event stream, and map to the unified trajectory protocol.

Why headless CLI (not the Claude Agent SDK) for this first-pass adapter:
  1. Headless CLI integration is what downstream teams actually ship — it's
     language-agnostic and runs wherever a subprocess can be spawned.
  2. No dependency on the claude-agent-sdk Python package, whose surface is
     evolving. The CLI's `stream-json` format is documented and stable.
  3. stream-json parsing is a concrete piece of engineering: content-block
     demultiplexing, tool_use_id propagation, error handling around process
     lifecycle. Good portfolio surface.

Dependency-free testing:
  `ClaudeCodeAdapter.from_stream(path)` parses a pre-recorded JSONL fixture
  into a trajectory. Conformance tests use this to verify the stream-json →
  protocol mapping without installing Claude Code.

stream-json event mapping:

  {"type":"system","subtype":"init",...}               → meta only (session id)
  {"type":"assistant","message":{"content":[...]}}     → walk content blocks:
     - {"type":"thinking","thinking":"..."}            → THOUGHT
     - {"type":"text","text":"..."}                    → THOUGHT (narration)
     - {"type":"tool_use","id":"...","name":"...","input":{...}}
                                                       → TOOL_CALL(call_id=id)
  {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":...,"content":...}]}}
                                                       → TOOL_RESULT(call_id)
  {"type":"result","result":"...",...}                 → FINAL_ANSWER
  anything unrecognized                                → attached to trajectory.meta.unhandled
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Iterable, Iterator, Optional

from ..agent import AnvilAgent, AnvilTask
from ..trajectory import EventKind, Trajectory


class ClaudeCodeAdapter(AnvilAgent):
    scaffold_name = "claude-code"

    def __init__(
        self,
        binary: str = "claude",
        extra_args: Optional[list[str]] = None,
        model: Optional[str] = None,
        timeout_seconds: int = 300,
        cwd: Optional[str] = None,
    ):
        self.binary = binary
        self.extra_args = list(extra_args or [])
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.cwd = cwd

    def run(self, task: AnvilTask) -> Trajectory:
        traj = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        traj.meta["protocol_version"] = "0.1"
        obs = task.initial_observation()
        traj.emit(EventKind.OBSERVATION, obs)

        try:
            stream = self._invoke(obs)
            self._map_stream(traj, stream)
        except FileNotFoundError as e:
            traj.emit(
                EventKind.ERROR,
                {"type": "ClaudeBinaryMissing", "message": str(e), "binary": self.binary},
            )
        except subprocess.TimeoutExpired as e:
            traj.emit(
                EventKind.ERROR,
                {"type": "TimeoutExpired", "message": str(e), "timeout": self.timeout_seconds},
            )
        except Exception as e:
            traj.emit(EventKind.ERROR, {"type": type(e).__name__, "message": str(e)})
        traj.finish()
        return traj

    def _invoke(self, obs: dict) -> Iterator[dict]:
        prompt = self._obs_to_prompt(obs)
        cmd = [
            self.binary,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        if self.model:
            cmd += ["--model", self.model]
        cmd += self.extra_args

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.cwd or os.getcwd(),
        )
        try:
            if proc.stdout is None:
                return iter(())
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
            proc.wait(timeout=self.timeout_seconds)
        finally:
            if proc.poll() is None:
                proc.kill()

    @staticmethod
    def _obs_to_prompt(obs: dict) -> str:
        text = obs.get("text", "")
        if obs.get("image_path"):
            text += f"\n\n[Reference image at: {obs['image_path']}]"
        return text

    @classmethod
    def from_stream(cls, stream_path: str | Path, task_id: str = "stream") -> Trajectory:
        """Parse a pre-recorded stream-json JSONL file into a trajectory.

        Used by tests and debug replay when the real Claude binary is not
        available. The resulting trajectory is protocol-compliant and can be
        validated with agentanvil.schema.validate().
        """
        events = []
        with open(stream_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        traj = Trajectory(task_id=task_id, scaffold=cls.scaffold_name)
        traj.meta["protocol_version"] = "0.1"
        traj.emit(EventKind.OBSERVATION, {"text": "(replayed from fixture)"})
        cls._map_stream(traj, events)
        traj.finish()
        return traj

    @staticmethod
    def _map_stream(traj: Trajectory, stream: Iterable[dict]) -> None:
        has_final = False
        for evt in stream:
            etype = evt.get("type")

            if etype == "system":
                if evt.get("subtype") == "init":
                    traj.meta["claude_session_id"] = evt.get("session_id")
                continue

            if etype == "assistant":
                blocks = (evt.get("message") or {}).get("content") or []
                for blk in blocks:
                    bt = blk.get("type")
                    if bt == "thinking":
                        traj.emit(
                            EventKind.THOUGHT,
                            {"text": blk.get("thinking", "")},
                            block="thinking",
                        )
                    elif bt == "text":
                        text = blk.get("text", "")
                        if text:
                            traj.emit(EventKind.THOUGHT, {"text": text}, block="text")
                    elif bt == "tool_use":
                        traj.emit(
                            EventKind.TOOL_CALL,
                            {
                                "name": blk.get("name"),
                                "arguments": blk.get("input"),
                                "call_id": blk.get("id"),
                            },
                            block="tool_use",
                        )
                continue

            if etype == "user":
                blocks = (evt.get("message") or {}).get("content") or []
                for blk in blocks:
                    if blk.get("type") == "tool_result":
                        output = blk.get("content")
                        if isinstance(output, list):
                            parts = [
                                b.get("text", "") if isinstance(b, dict) else str(b)
                                for b in output
                            ]
                            output = "".join(parts)
                        traj.emit(
                            EventKind.TOOL_RESULT,
                            {"call_id": blk.get("tool_use_id"), "output": output},
                            is_error=blk.get("is_error", False),
                        )
                continue

            if etype == "result":
                result_text = evt.get("result")
                if result_text is None:
                    result_text = (evt.get("message") or {}).get("content", "")
                traj.emit(
                    EventKind.FINAL_ANSWER,
                    str(result_text) if result_text is not None else "",
                    duration_ms=evt.get("duration_ms"),
                    total_cost_usd=evt.get("total_cost_usd"),
                )
                has_final = True
                continue

            traj.meta.setdefault("unhandled", []).append({"type": etype})

        if not has_final and not any(e.kind == EventKind.ERROR for e in traj.events):
            traj.emit(
                EventKind.ERROR,
                {"type": "NoResult", "message": "stream ended without a result event"},
            )
