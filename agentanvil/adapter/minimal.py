"""
Minimal adapter — direct LLM call, no scaffold.

Purpose:
  1. Forcing function for the trajectory protocol: if the protocol can't cleanly
     represent a bare LLM call, it's over-specified for downstream scaffolds.
  2. Baseline for comparison. Every other scaffold should beat (or at least
     match) this baseline on tasks where tool use isn't needed — if not, the
     scaffold is adding overhead without signal.
  3. Dependency-light default: runs with just `anthropic` or `openai` installed.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional

from ..agent import AnvilAgent, AnvilTask
from ..trajectory import EventKind, Trajectory


class MinimalAdapter(AnvilAgent):
    scaffold_name = "minimal"

    def __init__(
        self,
        provider: str = "anthropic",
        model: Optional[str] = None,
        max_tokens: int = 1024,
        system: Optional[str] = None,
    ):
        self.provider = provider
        self.model = model or self._default_model(provider)
        self.max_tokens = max_tokens
        self.system = system

    @staticmethod
    def _default_model(provider: str) -> str:
        if provider == "anthropic":
            return "claude-sonnet-4-6"
        if provider == "openai":
            return "gpt-5.4"
        raise ValueError(f"Unknown provider: {provider}")

    def run(self, task: AnvilTask) -> Trajectory:
        traj = Trajectory(task_id=task.task_id, scaffold=self.scaffold_name)
        obs = task.initial_observation()
        traj.emit(EventKind.OBSERVATION, obs)

        try:
            if self.provider == "anthropic":
                answer = self._call_anthropic(obs)
            elif self.provider == "openai":
                answer = self._call_openai(obs)
            else:
                raise ValueError(f"Unknown provider: {self.provider}")
            traj.emit(EventKind.FINAL_ANSWER, answer, model=self.model, provider=self.provider)
        except Exception as e:
            traj.emit(EventKind.ERROR, {"type": type(e).__name__, "message": str(e)})
        traj.finish()
        return traj

    def _call_anthropic(self, obs: dict) -> str:
        import anthropic

        client = anthropic.Anthropic()
        content = self._anthropic_content(obs)
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": content}],
        )
        if self.system:
            kwargs["system"] = self.system
        resp = client.messages.create(**kwargs)
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "\n".join(parts).strip()

    def _call_openai(self, obs: dict) -> str:
        import openai

        client = openai.OpenAI()
        content = self._openai_content(obs)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=self.max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()

    @staticmethod
    def _anthropic_content(obs: dict) -> list:
        parts: list = []
        img = obs.get("image_path")
        if img and Path(img).exists():
            b64 = base64.b64encode(Path(img).read_bytes()).decode()
            parts.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": b64},
                }
            )
        parts.append({"type": "text", "text": obs.get("text", "")})
        return parts

    @staticmethod
    def _openai_content(obs: dict):
        img = obs.get("image_path")
        text = obs.get("text", "")
        if img and Path(img).exists():
            b64 = base64.b64encode(Path(img).read_bytes()).decode()
            return [
                {"type": "text", "text": text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
            ]
        return text
