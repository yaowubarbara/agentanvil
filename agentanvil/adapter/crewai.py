"""
CrewAI adapter.

CrewAI is a role-based multi-agent framework. A `Crew` runs a `kickoff()`
cycle producing `CrewOutput` with `.tasks_output: list[TaskOutput]` and
`.raw` (final string). Each TaskOutput carries `agent`, `description`,
`raw`, `pydantic`, `json_dict`, and optional tool trace via
`token_usage.tool_calls` (newer versions).

Mapping:
  Each TaskOutput                           -> THOUGHT + (optional) TOOL_CALL/TOOL_RESULT pairs
  Tool usage objects on each task            -> TOOL_CALL + TOOL_RESULT with agent role
  CrewOutput.raw                             -> FINAL_ANSWER

We capture `agent` (role name) in event.meta so the diff UI can show which
agent said what.
"""
from __future__ import annotations

from typing import Any, Callable

from ..agent import AnvilAgent, AnvilTask
from ..trajectory import EventKind, Trajectory


class CrewAIAdapter(AnvilAgent):
    scaffold_name = "crewai"

    def __init__(self, crew: Any = None, run_fn: Callable[[Any, dict], Any] | None = None):
        self.crew = crew
        self.run_fn = run_fn or (lambda c, inputs: c.kickoff(inputs=inputs))

    def run(self, task: AnvilTask) -> Trajectory:
        traj = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        traj.meta["protocol_version"] = "0.1"
        obs = task.initial_observation()
        traj.emit(EventKind.OBSERVATION, obs)

        try:
            result = self.run_fn(self.crew, {"prompt": obs.get("text", "")})
            self._map_result(traj, result)
        except Exception as e:
            traj.emit(EventKind.ERROR, {"type": type(e).__name__, "message": str(e)})
        traj.finish()
        return traj

    @staticmethod
    def _map_result(traj: Trajectory, result: Any) -> None:
        tasks_output = getattr(result, "tasks_output", None) or []
        for t_out in tasks_output:
            agent = getattr(t_out, "agent", None) or getattr(t_out, "agent_role", None) or "unknown"
            description = getattr(t_out, "description", None) or ""
            raw = getattr(t_out, "raw", None) or str(t_out)
            tool_calls = getattr(t_out, "tool_calls", None) or getattr(t_out, "tools_used", None) or []

            if description:
                traj.emit(
                    EventKind.THOUGHT,
                    {"text": f"[{agent}] planning: {description}"},
                    agent=agent,
                    crewai="TaskDescription",
                )

            for tc in tool_calls:
                traj.emit(
                    EventKind.TOOL_CALL,
                    {
                        "name": getattr(tc, "tool_name", None) or getattr(tc, "tool", "unknown"),
                        "arguments": getattr(tc, "arguments", None) or getattr(tc, "tool_input", None),
                        "call_id": getattr(tc, "id", None),
                    },
                    agent=agent,
                    crewai="ToolCall",
                )
                traj.emit(
                    EventKind.TOOL_RESULT,
                    {
                        "call_id": getattr(tc, "id", None),
                        "output": getattr(tc, "result", None) or getattr(tc, "output", str(tc)),
                    },
                    agent=agent,
                    crewai="ToolResult",
                )

            traj.emit(
                EventKind.THOUGHT,
                {"text": f"[{agent}] result: {raw}"},
                agent=agent,
                crewai="TaskResult",
            )

        final = getattr(result, "raw", None)
        if final is None:
            final = str(result)
        traj.emit(EventKind.FINAL_ANSWER, final)


def from_tasks_output(task_id: str, tasks_output: list, final_raw: str) -> Trajectory:
    class _T(AnvilTask):
        def __init__(self, tid):
            self.task_id = tid

        def initial_observation(self) -> dict:
            return {"text": "(replayed from CrewAI fixture)"}

    class _Result:
        def __init__(self, tasks_output, raw):
            self.tasks_output = tasks_output
            self.raw = raw

    adapter = CrewAIAdapter(run_fn=lambda _c, _i: _Result(tasks_output, final_raw))
    return adapter.run(_T(task_id))
