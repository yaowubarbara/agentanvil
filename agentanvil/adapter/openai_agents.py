"""
OpenAI Agents SDK adapter.

Wraps `openai-agents` Runner into the AnvilAgent contract and maps
SDK RunItems to our unified trajectory events.

Chosen as the first "real scaffold" adapter because:
  - Protocol is well-defined (function calling + tool schema), instrumentation
    boundaries are clean.
  - Python-native SDK, no subprocess management required.
  - Broad industry coverage — if the harness can host OpenAI Agents SDK, most
    teams can onboard without friction.

Phase 0 status: skeleton. The item-classification logic is defensive (getattr +
str fallback) so small SDK API drifts do not break the harness; Phase 1 tightens
this with version-pinned mappings and schema validation.
"""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any, Optional

from ..agent import AnvilAgent, AnvilTask
from ..trajectory import EventKind, Trajectory


class OpenAIAgentsAdapter(AnvilAgent):
    scaffold_name = "openai-agents-sdk"

    def __init__(self, agent: Any, max_turns: int = 10):
        """
        agent: a pre-configured `agents.Agent` instance (model, tools, instructions
               are the caller's responsibility — we do not wrap that config here).
        """
        self.agent = agent
        self.max_turns = max_turns

    def run(self, task: AnvilTask) -> Trajectory:
        from agents import Runner

        traj = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        obs = task.initial_observation()
        traj.emit(EventKind.OBSERVATION, obs)

        try:
            input_items = self._to_input_items(obs)
            result = asyncio.run(
                Runner.run(self.agent, input=input_items, max_turns=self.max_turns)
            )
            for item in getattr(result, "new_items", []):
                kind, content, meta = self._classify(item)
                traj.emit(kind, content, **meta)
            final = getattr(result, "final_output", None)
            traj.emit(EventKind.FINAL_ANSWER, str(final) if final is not None else "")
        except Exception as e:
            traj.emit(EventKind.ERROR, {"type": type(e).__name__, "message": str(e)})
        traj.finish()
        return traj

    @staticmethod
    def _to_input_items(obs: dict) -> list:
        text = obs.get("text", "")
        img = obs.get("image_path")
        if img and Path(img).exists():
            b64 = base64.b64encode(Path(img).read_bytes()).decode()
            return [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": text},
                        {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{b64}",
                        },
                    ],
                }
            ]
        return [{"role": "user", "content": text}]

    @staticmethod
    def _classify(item: Any) -> tuple[EventKind, Any, dict]:
        """Map an openai-agents RunItem to a trajectory event.

        The SDK's concrete item classes are subject to change; we classify by
        class name substring to degrade gracefully on minor version bumps.
        """
        cls = type(item).__name__
        meta = {"sdk_item": cls}

        if "ToolCall" in cls:
            return (
                EventKind.TOOL_CALL,
                {
                    "name": getattr(item, "tool_name", None) or getattr(item, "name", None),
                    "arguments": getattr(item, "input", None) or getattr(item, "arguments", None),
                },
                meta,
            )
        if "ToolOutput" in cls or "ToolResult" in cls:
            return (
                EventKind.TOOL_RESULT,
                {"output": getattr(item, "output", None) or str(item)},
                meta,
            )
        if "Reasoning" in cls:
            return (EventKind.THOUGHT, {"text": str(item)}, meta)
        if "Message" in cls:
            content = getattr(item, "content", None) or str(item)
            return (EventKind.THOUGHT, {"text": str(content)}, meta)
        return (EventKind.THOUGHT, {"raw": str(item)}, meta)
