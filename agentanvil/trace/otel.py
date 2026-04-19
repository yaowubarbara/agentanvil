"""
OpenTelemetry exporter.

Emits one span per trajectory event, bundled under a root span named
"agentanvil.trajectory". Works with any OTel-compatible backend (Jaeger,
Tempo, Honeycomb, Datadog, Arize Phoenix OpenInference).

Design choices:
  - Import opentelemetry lazily — the dep is optional. AgentAnvil stays
    pure-stdlib when OTel isn't installed.
  - Propagate trajectory_id as trace_id-like attribute + task_id/scaffold as
    span resource attributes for filtering.
  - Tool calls get span kind CLIENT; tool results are events on that span.
  - Reward appears on the root span as an attribute + a separate metric
    (if a meter provider is configured).

Installation:
  pip install 'agentanvil[otel]'   # (add opentelemetry deps to pyproject extras)
"""
from __future__ import annotations

import time
from typing import Optional

from ..trajectory import EventKind, Trajectory
from ..verifier.base import VerifyResult
from .base import TraceSink


class OpenTelemetrySink(TraceSink):
    def __init__(
        self,
        service_name: str = "agentanvil",
        tracer_provider=None,
    ):
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.resources import Resource
        except ImportError as e:
            raise ImportError(
                "OpenTelemetrySink requires `pip install opentelemetry-api opentelemetry-sdk`"
            ) from e

        if tracer_provider is None:
            provider = TracerProvider(
                resource=Resource.create({"service.name": service_name})
            )
            trace.set_tracer_provider(provider)
        self.tracer = trace.get_tracer("agentanvil", "0.0.2")
        self.service_name = service_name

    def write(self, traj: Trajectory, verify_result: Optional[VerifyResult] = None) -> None:
        with self.tracer.start_as_current_span(
            "agentanvil.trajectory",
            start_time=int(traj.started_at * 1e9),
            attributes={
                "agentanvil.trajectory_id": traj.trajectory_id,
                "agentanvil.task_id": traj.task_id,
                "agentanvil.scaffold": traj.scaffold,
                "agentanvil.protocol_version": traj.meta.get("protocol_version", "0.1"),
            },
            end_on_exit=False,
        ) as root:
            for event in traj.events:
                self._emit_event_span(event, parent=root)
            if verify_result is not None:
                root.set_attribute("agentanvil.reward", float(verify_result.reward))
                root.set_attribute("agentanvil.correct", bool(verify_result.correct))
                root.set_attribute("agentanvil.parsed", str(verify_result.parsed))
                root.set_attribute("agentanvil.gold", str(verify_result.gold))
            finish_ns = int((traj.finished_at or time.time()) * 1e9)
            root.end(end_time=finish_ns)

    def _emit_event_span(self, event, parent) -> None:
        start_ns = int(event.ts * 1e9)
        attrs = {
            "agentanvil.event.kind": event.kind.value,
            "agentanvil.event.step": event.step,
        }
        if event.kind == EventKind.TOOL_CALL and isinstance(event.content, dict):
            attrs["agentanvil.tool.name"] = str(event.content.get("name", ""))
            if event.content.get("call_id"):
                attrs["agentanvil.tool.call_id"] = str(event.content.get("call_id"))
        for k, v in (event.meta or {}).items():
            attrs[f"agentanvil.meta.{k}"] = str(v)
        with self.tracer.start_as_current_span(
            f"event.{event.kind.value}",
            start_time=start_ns,
            attributes=attrs,
            end_on_exit=False,
        ) as span:
            span.end(end_time=start_ns + 1000)  # 1µs synthetic span width
