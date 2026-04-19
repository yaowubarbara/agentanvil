"""
AutoGen adapter (Microsoft AutoGen v0.4+).

AutoGen uses a multi-agent chat model; conversations surface as a list of
`ChatMessage` subtypes: TextMessage, ToolCallRequestEvent, ToolCallExecutionEvent,
ThoughtEvent (on newer builds), HandoffMessage, StopMessage.

Mapping:
  TextMessage / ThoughtEvent                -> THOUGHT
  ToolCallRequestEvent                      -> TOOL_CALL (name + args + id)
  ToolCallExecutionEvent / ToolCallSummaryMessage
                                            -> TOOL_RESULT
  HandoffMessage                            -> THOUGHT with meta.handoff_to
  StopMessage (or .stop_reason != None)     -> FINAL_ANSWER

The `Runner` (`RoundRobinGroupChat` or similar) produces a `TaskResult` with
`.messages: list[ChatMessage]`. The caller runs the team; this adapter
converts `task_result.messages`.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from ..agent import AnvilAgent, AnvilTask
from ..trajectory import EventKind, Trajectory


class AutoGenAdapter(AnvilAgent):
    scaffold_name = "autogen"

    def __init__(self, team: Any = None, run_fn: Callable[[Any, str], Any] | None = None):
        """
        team: an AutoGen `BaseGroupChat` or agent. If None, rely on run_fn for
          testability.
        run_fn: callable(team, prompt) -> TaskResult-shaped object with
          `.messages` and `.stop_reason`. Defaults to calling `team.run(task=...)`.
        """
        self.team = team
        self.run_fn = run_fn or (lambda t, p: t.run(task=p))

    def run(self, task: AnvilTask) -> Trajectory:
        traj = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        traj.meta["protocol_version"] = "0.1"
        obs = task.initial_observation()
        traj.emit(EventKind.OBSERVATION, obs)

        try:
            prompt = obs.get("text", "")
            result = self.run_fn(self.team, prompt)
            self._map_result(traj, result)
        except Exception as e:
            traj.emit(EventKind.ERROR, {"type": type(e).__name__, "message": str(e)})
        traj.finish()
        return traj

    @staticmethod
    def _map_result(traj: Trajectory, result: Any) -> None:
        messages = getattr(result, "messages", None) or []
        stop_reason = getattr(result, "stop_reason", None)
        final_content: str | None = None

        for msg in messages:
            cls = type(msg).__name__
            if cls in ("TextMessage", "ThoughtEvent"):
                source = getattr(msg, "source", "agent")
                content = getattr(msg, "content", str(msg))
                if source == "user":
                    continue
                traj.emit(EventKind.THOUGHT, {"text": str(content), "source": source}, autogen=cls)
                final_content = str(content)
                continue
            if cls == "ToolCallRequestEvent":
                calls = getattr(msg, "content", None) or []
                for call in calls:
                    traj.emit(
                        EventKind.TOOL_CALL,
                        {
                            "name": getattr(call, "name", None),
                            "arguments": getattr(call, "arguments", None),
                            "call_id": getattr(call, "id", None),
                        },
                        autogen=cls,
                    )
                continue
            if cls in ("ToolCallExecutionEvent", "ToolCallSummaryMessage"):
                results = getattr(msg, "content", None) or []
                if isinstance(results, list):
                    for r in results:
                        traj.emit(
                            EventKind.TOOL_RESULT,
                            {
                                "call_id": getattr(r, "call_id", None),
                                "output": getattr(r, "content", str(r)),
                                "is_error": getattr(r, "is_error", False),
                            },
                            autogen=cls,
                        )
                else:
                    traj.emit(EventKind.TOOL_RESULT, {"output": str(results)}, autogen=cls)
                continue
            if cls == "HandoffMessage":
                traj.emit(
                    EventKind.THOUGHT,
                    {"text": f"handoff from {getattr(msg, 'source', '?')} to {getattr(msg, 'target', '?')}"},
                    handoff_to=getattr(msg, "target", None),
                    autogen=cls,
                )
                continue
            traj.meta.setdefault("unhandled_autogen", []).append(cls)

        final = final_content if final_content is not None else (str(stop_reason) if stop_reason else "")
        traj.emit(EventKind.FINAL_ANSWER, final, stop_reason=str(stop_reason) if stop_reason else None)


def from_messages(task_id: str, messages: list, stop_reason: str = "stop") -> Trajectory:
    """Dep-free helper: wrap a pre-recorded message list into a trajectory."""

    class _T(AnvilTask):
        def __init__(self, tid):
            self.task_id = tid

        def initial_observation(self) -> dict:
            return {"text": "(replayed from AutoGen message fixture)"}

    class _Result:
        def __init__(self, messages, stop_reason):
            self.messages = messages
            self.stop_reason = stop_reason

    adapter = AutoGenAdapter(run_fn=lambda _t, _p: _Result(messages, stop_reason))
    return adapter.run(_T(task_id))
