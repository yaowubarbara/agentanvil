"""
LlamaIndex Agent adapter.

LlamaIndex ships two agent generations:
  - Legacy: `ReActAgent` / `OpenAIAgent` with `.chat(prompt)` returning `AgentChatResponse`
    whose `.sources` is a list of ToolOutputs.
  - Workflow-based (llama-index v0.12+): `AgentWorkflow` with event stream
    (AgentInput, AgentOutput, AgentStream, ToolCall, ToolCallResult).

This adapter handles both. For the legacy API it inspects `.sources`;
for workflows it consumes the async event stream in a sync wrapper.

Mapping:
  AgentInput / AgentStream (reasoning text) -> THOUGHT
  ToolCall                                   -> TOOL_CALL
  ToolCallResult                             -> TOOL_RESULT (pair by tool_id)
  AgentOutput.response / AgentChatResponse.response -> FINAL_ANSWER
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from ..agent import AnvilAgent, AnvilTask
from ..trajectory import EventKind, Trajectory


class LlamaIndexAdapter(AnvilAgent):
    scaffold_name = "llamaindex"

    def __init__(
        self,
        agent: Any = None,
        mode: str = "auto",
        run_fn: Callable[[Any, str], Any] | None = None,
    ):
        """
        mode: "legacy" | "workflow" | "auto" (detect from class name).
        """
        self.agent = agent
        self.mode = mode
        self.run_fn = run_fn

    def run(self, task: AnvilTask) -> Trajectory:
        traj = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        traj.meta["protocol_version"] = "0.1"
        obs = task.initial_observation()
        traj.emit(EventKind.OBSERVATION, obs)

        try:
            prompt = obs.get("text", "")
            if self.run_fn is not None:
                result = self.run_fn(self.agent, prompt)
                self._map_generic(traj, result)
            else:
                mode = self.mode
                if mode == "auto":
                    mode = "workflow" if "workflow" in type(self.agent).__name__.lower() else "legacy"
                if mode == "legacy":
                    self._run_legacy(traj, prompt)
                else:
                    self._run_workflow(traj, prompt)
        except Exception as e:
            traj.emit(EventKind.ERROR, {"type": type(e).__name__, "message": str(e)})
        traj.finish()
        return traj

    def _run_legacy(self, traj: Trajectory, prompt: str) -> None:
        response = self.agent.chat(prompt)
        sources = getattr(response, "sources", None) or []
        for src in sources:
            tool_name = getattr(src, "tool_name", None) or "unknown"
            tool_input = getattr(src, "raw_input", None) or getattr(src, "content", None)
            tool_out = getattr(src, "raw_output", None) or getattr(src, "content", str(src))
            call_id = getattr(src, "tool_id", None) or f"li-{id(src)}"
            traj.emit(
                EventKind.TOOL_CALL,
                {"name": tool_name, "arguments": tool_input, "call_id": call_id},
                llamaindex="legacy_source",
            )
            traj.emit(
                EventKind.TOOL_RESULT,
                {"call_id": call_id, "output": tool_out},
                llamaindex="legacy_source",
            )
        final = getattr(response, "response", None) or str(response)
        traj.emit(EventKind.FINAL_ANSWER, str(final))

    def _run_workflow(self, traj: Trajectory, prompt: str) -> None:
        async def drive():
            handler = self.agent.run(user_msg=prompt)
            events = []
            async for ev in handler.stream_events():
                events.append(ev)
            result = await handler
            return events, result

        events, result = asyncio.run(drive())
        for ev in events:
            cls = type(ev).__name__
            if cls in ("AgentInput", "AgentStream"):
                txt = getattr(ev, "delta", None) or getattr(ev, "response", None) or str(ev)
                if txt:
                    traj.emit(EventKind.THOUGHT, {"text": str(txt)}, llamaindex=cls)
            elif cls == "ToolCall":
                traj.emit(
                    EventKind.TOOL_CALL,
                    {
                        "name": getattr(ev, "tool_name", None),
                        "arguments": getattr(ev, "tool_kwargs", None) or getattr(ev, "tool_args", None),
                        "call_id": getattr(ev, "tool_id", None),
                    },
                    llamaindex=cls,
                )
            elif cls == "ToolCallResult":
                traj.emit(
                    EventKind.TOOL_RESULT,
                    {
                        "call_id": getattr(ev, "tool_id", None),
                        "output": getattr(ev, "tool_output", None) or str(ev),
                    },
                    llamaindex=cls,
                )
        final = getattr(result, "response", None) or str(result)
        traj.emit(EventKind.FINAL_ANSWER, str(final))

    @staticmethod
    def _map_generic(traj: Trajectory, result: Any) -> None:
        """Called when a custom run_fn is provided; expects either a
        list of event objects or a response-like object with .response."""
        if isinstance(result, list):
            for ev in result:
                cls = type(ev).__name__
                if "Tool" in cls and "Result" in cls:
                    traj.emit(EventKind.TOOL_RESULT, {"output": str(ev)}, llamaindex=cls)
                elif "Tool" in cls:
                    traj.emit(EventKind.TOOL_CALL, {"name": cls, "arguments": None}, llamaindex=cls)
                else:
                    traj.emit(EventKind.THOUGHT, {"text": str(ev)}, llamaindex=cls)
            traj.emit(EventKind.FINAL_ANSWER, "")
        else:
            final = getattr(result, "response", None) or str(result)
            traj.emit(EventKind.FINAL_ANSWER, str(final))
