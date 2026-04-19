"""
LangGraph adapter.

LangGraph is a stateful-graph agent framework from LangChain. Execution
produces a stream of state dicts — one per node invocation — or a final
`output_state` from `graph.invoke(state)`.

Mapping:
  Each state transition                     -> THOUGHT (contains node name)
  state['messages'] AIMessage w/ tool_calls -> TOOL_CALL
  state['messages'] ToolMessage             -> TOOL_RESULT (by tool_call_id)
  Final state's last AIMessage.content      -> FINAL_ANSWER

Because LangGraph's state schema is user-defined, we look for the conventional
`messages` channel (from `langgraph.graph.MessagesState`). Adapters for custom
state schemas can subclass and override `_extract_messages`.
"""
from __future__ import annotations

from typing import Any, Callable

from ..agent import AnvilAgent, AnvilTask
from ..trajectory import EventKind, Trajectory


class LangGraphAdapter(AnvilAgent):
    scaffold_name = "langgraph"

    def __init__(self, graph: Any = None, stream_fn: Callable[[Any, dict], Any] | None = None):
        self.graph = graph
        self.stream_fn = stream_fn or (lambda g, s: list(g.stream(s, stream_mode="values")))

    def run(self, task: AnvilTask) -> Trajectory:
        traj = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        traj.meta["protocol_version"] = "0.1"
        obs = task.initial_observation()
        traj.emit(EventKind.OBSERVATION, obs)

        try:
            initial_state = {"messages": [{"role": "user", "content": obs.get("text", "")}]}
            states = self.stream_fn(self.graph, initial_state)
            self._map_states(traj, states)
        except Exception as e:
            traj.emit(EventKind.ERROR, {"type": type(e).__name__, "message": str(e)})
        traj.finish()
        return traj

    @staticmethod
    def _map_states(traj: Trajectory, states: list) -> None:
        seen_message_ids: set[str] = set()
        final_text: str | None = None

        for state_idx, state in enumerate(states):
            node = state.get("__node__") if isinstance(state, dict) else None
            messages = LangGraphAdapter._extract_messages(state)
            for msg in messages:
                msg_id = LangGraphAdapter._msg_id(msg)
                if msg_id in seen_message_ids:
                    continue
                seen_message_ids.add(msg_id)
                role, content, tool_calls, tool_call_id = LangGraphAdapter._unpack_msg(msg)
                if role == "user":
                    continue
                if role in ("ai", "assistant"):
                    if content:
                        traj.emit(
                            EventKind.THOUGHT,
                            {"text": str(content)},
                            node=node,
                            state_idx=state_idx,
                        )
                        final_text = str(content)
                    for tc in tool_calls or []:
                        traj.emit(
                            EventKind.TOOL_CALL,
                            {
                                "name": tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None),
                                "arguments": tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None),
                                "call_id": tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None),
                            },
                            node=node,
                            state_idx=state_idx,
                        )
                elif role == "tool":
                    traj.emit(
                        EventKind.TOOL_RESULT,
                        {"call_id": tool_call_id, "output": str(content)},
                        node=node,
                        state_idx=state_idx,
                    )
        traj.emit(EventKind.FINAL_ANSWER, final_text if final_text is not None else "")

    @staticmethod
    def _extract_messages(state: Any) -> list:
        if isinstance(state, dict):
            return state.get("messages", []) or []
        return getattr(state, "messages", []) or []

    @staticmethod
    def _msg_id(msg: Any) -> str:
        if isinstance(msg, dict):
            return msg.get("id") or str(id(msg))
        return getattr(msg, "id", None) or str(id(msg))

    @staticmethod
    def _unpack_msg(msg: Any):
        if isinstance(msg, dict):
            return (
                msg.get("role") or msg.get("type", "unknown"),
                msg.get("content"),
                msg.get("tool_calls"),
                msg.get("tool_call_id"),
            )
        cls = type(msg).__name__.lower()
        role = (
            "user" if "human" in cls
            else "ai" if "ai" in cls or "assistant" in cls
            else "tool" if "tool" in cls
            else "unknown"
        )
        return (
            role,
            getattr(msg, "content", None),
            getattr(msg, "tool_calls", None),
            getattr(msg, "tool_call_id", None),
        )


def from_states(task_id: str, states: list) -> Trajectory:
    class _T(AnvilTask):
        def __init__(self, tid):
            self.task_id = tid

        def initial_observation(self) -> dict:
            return {"text": "(replayed from LangGraph states fixture)"}

    adapter = LangGraphAdapter(stream_fn=lambda _g, _s: states)
    return adapter.run(_T(task_id))
