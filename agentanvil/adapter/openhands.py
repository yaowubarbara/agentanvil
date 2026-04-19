"""
OpenHands (formerly OpenDevin) adapter.

OpenHands is an open-source autonomous code agent. Its event model is a stream
of typed Action/Observation records:

  Action types     — MessageAction, CmdRunAction, IPythonRunCellAction,
                     FileEditAction, FileReadAction, BrowseURLAction, AgentFinishAction
  Observation types— CmdOutputObservation, IPythonRunCellObservation,
                     FileEditObservation, FileReadObservation, ErrorObservation

Our mapping strategy:
  - MessageAction with source='agent'       -> THOUGHT
  - *Action (code/file/browse/cmd)          -> TOOL_CALL (name=class, args=__dict__)
  - *Observation                             -> TOOL_RESULT
  - AgentFinishAction                        -> FINAL_ANSWER
  - ErrorObservation                         -> ERROR

OpenHands exposes events via `controller.event_stream`. The caller is
responsible for driving the controller loop; this adapter converts the
collected event list.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from ..agent import AnvilAgent, AnvilTask
from ..trajectory import EventKind, Trajectory


class OpenHandsAdapter(AnvilAgent):
    scaffold_name = "openhands"

    def __init__(self, controller: Any = None, event_collector: Callable[[Any], list] | None = None):
        """
        controller: an OpenHands AgentController (or equivalent). If None, you
          must pass event_collector — useful for tests that supply a
          pre-recorded event list.
        event_collector: given the controller (or None), return a list of
          OpenHands Action/Observation objects for this task.
        """
        if controller is None and event_collector is None:
            raise ValueError("Provide either `controller` or `event_collector`.")
        self.controller = controller
        self.event_collector = event_collector or (lambda c: list(c.event_stream.get_events()))

    def run(self, task: AnvilTask) -> Trajectory:
        traj = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        traj.meta["protocol_version"] = "0.1"
        obs = task.initial_observation()
        traj.emit(EventKind.OBSERVATION, obs)

        try:
            events = self.event_collector(self.controller)
            self._map_events(traj, events)
        except Exception as e:
            traj.emit(EventKind.ERROR, {"type": type(e).__name__, "message": str(e)})
        traj.finish()
        return traj

    @staticmethod
    def _map_events(traj: Trajectory, events: Iterable[Any]) -> None:
        open_tool_ids: dict[int, str] = {}
        step = 1
        seen_final = False
        for event in events:
            cls = type(event).__name__
            if cls == "MessageAction":
                source = getattr(event, "source", "agent")
                content = getattr(event, "content", str(event))
                if source == "agent":
                    traj.emit(EventKind.THOUGHT, {"text": content}, oh_event=cls)
                continue
            if cls == "AgentFinishAction":
                final = getattr(event, "outputs", None) or getattr(event, "thought", None) or str(event)
                traj.emit(EventKind.FINAL_ANSWER, final if isinstance(final, str) else str(final))
                seen_final = True
                continue
            if cls == "ErrorObservation":
                traj.emit(
                    EventKind.ERROR,
                    {"type": "OpenHandsError", "message": getattr(event, "content", str(event))},
                )
                continue
            if cls.endswith("Action"):
                call_id = f"oh-{id(event)}"
                args = _to_args(event)
                traj.emit(
                    EventKind.TOOL_CALL,
                    {"name": cls, "arguments": args, "call_id": call_id},
                    oh_event=cls,
                )
                open_tool_ids[id(event)] = call_id
                continue
            if cls.endswith("Observation"):
                paired = None
                if open_tool_ids:
                    _, paired = open_tool_ids.popitem()
                traj.emit(
                    EventKind.TOOL_RESULT,
                    {
                        "output": getattr(event, "content", str(event)),
                        **({"call_id": paired} if paired else {}),
                    },
                    oh_event=cls,
                )
                continue
            traj.meta.setdefault("unhandled", []).append(cls)
        if not seen_final and not any(e.kind == EventKind.ERROR for e in traj.events[1:]):
            traj.emit(
                EventKind.ERROR,
                {"type": "NoFinish", "message": "event stream ended without AgentFinishAction"},
            )


def _to_args(event: Any) -> dict:
    """Coerce an Action object to a JSON-serializable arg dict."""
    out: dict = {}
    for k, v in (getattr(event, "__dict__", {}) or {}).items():
        if k.startswith("_"):
            continue
        try:
            import json

            json.dumps(v)
            out[k] = v
        except (TypeError, ValueError):
            out[k] = str(v)
    return out


def from_events(task_id: str, events: list) -> Trajectory:
    """Dep-free helper for tests: wrap a raw events list into a trajectory."""

    class _T(AnvilTask):
        def __init__(self, tid):
            self.task_id = tid

        def initial_observation(self) -> dict:
            return {"text": "(replayed from OpenHands event fixture)"}

    adapter = OpenHandsAdapter(event_collector=lambda _c: events)
    return adapter.run(_T(task_id))
