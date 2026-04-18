"""
LangChain adapter.

Wraps a LangChain AgentExecutor (or any Runnable that returns
`{"output": str, "intermediate_steps": list[(AgentAction, str)]}`) into the
AnvilAgent contract.

Chosen as the third Phase 1 scaffold because:
  1. LangChain is explicitly named in the target JD.
  2. It genuinely exercises the tool_call / tool_result pair path, which
     minimal (no tools) and a single-turn OpenAI Agents SDK invocation may
     not hit — useful pressure on the protocol.
  3. pip-only install, no Docker dependency.

The `intermediate_steps` surface is stable across LangChain 0.1 / 0.2 / 0.3.
Recent versions (0.3+) expose tool_call_id on AgentAction subclasses; we
capture it if present and leave it empty otherwise (pair by order).
"""
from __future__ import annotations

from typing import Any, Callable

from ..agent import AnvilAgent, AnvilTask
from ..trajectory import EventKind, Trajectory


class LangChainAdapter(AnvilAgent):
    scaffold_name = "langchain"

    def __init__(self, executor: Any, input_key: str = "input"):
        """
        executor: a LangChain AgentExecutor (or compatible Runnable). The caller
          is responsible for configuring the LLM, tools, and prompt — this
          adapter only wraps invocation + event mapping.
        input_key: the input key the executor expects (default "input").
        """
        self.executor = executor
        self.input_key = input_key

    def run(self, task: AnvilTask) -> Trajectory:
        traj = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        traj.meta["protocol_version"] = "0.1"
        obs = task.initial_observation()
        traj.emit(EventKind.OBSERVATION, obs)

        try:
            prompt = self._obs_to_prompt(obs)
            payload = {self.input_key: prompt}
            result = self.executor.invoke(payload)
            self._emit_intermediate_steps(traj, result.get("intermediate_steps", []))
            output = result.get("output", "")
            traj.emit(EventKind.FINAL_ANSWER, str(output))
        except Exception as e:
            traj.emit(EventKind.ERROR, {"type": type(e).__name__, "message": str(e)})
        traj.finish()
        return traj

    @staticmethod
    def _obs_to_prompt(obs: dict) -> str:
        text = obs.get("text", "")
        if obs.get("image_path"):
            text += f"\n\n[Image attached at path: {obs['image_path']}]"
        return text

    @staticmethod
    def _emit_intermediate_steps(traj: Trajectory, steps: list) -> None:
        for action, observation in steps:
            name = getattr(action, "tool", None) or getattr(action, "name", "unknown")
            args = getattr(action, "tool_input", None)
            if args is None:
                args = getattr(action, "input", None)
            call_id = (
                getattr(action, "tool_call_id", None)
                or getattr(action, "id", None)
            )
            content: dict = {"name": name, "arguments": args}
            if call_id:
                content["call_id"] = call_id
            meta = {"lc_log": getattr(action, "log", None)}
            traj.emit(EventKind.TOOL_CALL, content, **meta)

            result_content: dict = {"output": observation}
            if call_id:
                result_content["call_id"] = call_id
            traj.emit(EventKind.TOOL_RESULT, result_content)


def from_callable(fn: Callable[[str], dict], input_key: str = "input") -> LangChainAdapter:
    """Escape hatch for tests and ad-hoc runs: wrap a plain callable that
    returns {'output': str, 'intermediate_steps': [...]} as if it were an
    AgentExecutor. Lets conformance tests run without installing langchain."""

    class _FakeExecutor:
        def invoke(self, payload):
            return fn(payload[input_key])

    return LangChainAdapter(_FakeExecutor(), input_key=input_key)
