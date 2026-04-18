# Unified Trajectory Protocol — v0.1

> **Status**: Draft. Stabilizing in Phase 1. Subject to additive changes (minor version bumps); breaking changes require a major version bump and a migration note.

## 1. Motivation

Every agent scaffold (OpenAI Agents SDK, Claude Code, OpenHands, LangChain, and so on) has its own trace representation. That makes three things painful:

1. **Cross-scaffold evaluation.** You can't compare apples to apples without a lingua franca.
2. **Replay tooling.** Every new scaffold means a new viewer, or a shared viewer that's a union of shapes.
3. **RL integration.** An RL trainer needs to consume rollouts from many scaffolds; if the shape varies, every adapter must be taught to the trainer separately.

The Unified Trajectory Protocol is the narrow lingua franca. It is deliberately **not** a faithful reconstruction of any scaffold's internal state — faithful replay of a scaffold's internals is that scaffold's own concern. This protocol captures exactly what evaluation, replay, and RL need, and no more.

## 2. Design principles

- **Flat, not tree.** A trajectory is a linear sequence of events. Sub-agents, handoffs, and parallel tool calls are modeled by metadata on events, not by nesting.
- **Minimal required surface.** Every field is either required (strict shape) or in `meta` (free-form). There is no third category.
- **JSON-serializable.** Every event, every content, every meta value must round-trip through `json.dumps`/`json.loads` without information loss. If a scaffold has a non-serializable object, the adapter converts to a serializable representation (usually a string or dict) before emitting.
- **Scaffold-agnostic core + scaffold-specific meta.** Adapters MAY attach arbitrary keys under `meta` to preserve scaffold-specific richness. Consumers MUST ignore meta keys they don't understand.
- **Terminal reward.** A trajectory ends with either a `final_answer` (success path) or an `error` (failure path). The verifier emits a `reward` event after scoring. Credit assignment strategies that split reward over intermediate events live outside this protocol.

## 3. Top-level structure

```jsonc
{
  "trajectory_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_id": "jordan_count/task_000",
  "scaffold": "openai-agents-sdk",
  "started_at": 1713458123.41,
  "finished_at": 1713458127.88,
  "meta": { "protocol_version": "0.1" },
  "events": [ /* ... */ ]
}
```

| Field            | Type     | Required | Notes                                                                 |
| ---------------- | -------- | -------- | --------------------------------------------------------------------- |
| `trajectory_id`  | string   | yes      | UUIDv4 recommended. Unique per run.                                   |
| `task_id`        | string   | yes      | Identifies the task. Convention: `<suite>/<id>`.                      |
| `scaffold`       | string   | yes      | Lowercased kebab-case scaffold identifier.                            |
| `started_at`     | number   | yes      | Unix seconds, float.                                                  |
| `finished_at`    | number\|null | yes  | Unix seconds when the run terminated; null if still running.          |
| `meta`           | object   | yes      | At minimum contains `protocol_version`. Free-form otherwise.          |
| `events`         | array    | yes      | Non-empty. See §4.                                                    |

## 4. Event types

Every event has this core shape:

```jsonc
{
  "kind": "<EventKind>",
  "content": <kind-specific>,
  "step": 0,
  "ts": 1713458123.41,
  "meta": { }
}
```

Rules:
- `step` is a contiguous non-negative integer starting at 0, strictly increasing in the events array.
- `ts` is Unix seconds, float, non-decreasing (events may share a timestamp but cannot go backward).
- `content` shape depends on `kind`, described below.
- `meta` is always present (may be empty).

### 4.1 `observation` — environment → agent

```jsonc
{"text": "string", "image_path": "optional/abs/path", "image_base64": "optional-b64", "messages": [/* optional legacy chat history */]}
```

At least one of `text`, `image_path`, `image_base64`, or `messages` MUST be present. Adapters consume what they can; extra keys are ignored.

### 4.2 `thought` — agent internal

```jsonc
{"text": "string"}
```

Chain-of-thought, reasoning traces, planning output. If the scaffold exposes structured reasoning (e.g. Claude extended thinking blocks), flatten to text and attach structured form under `meta`.

### 4.3 `tool_call` — agent → environment

```jsonc
{"name": "string", "arguments": <object|string>, "call_id": "optional-string"}
```

**Normalization across scaffolds:**

| Scaffold            | Native shape                       | Mapping                                                     |
| ------------------- | ---------------------------------- | ----------------------------------------------------------- |
| OpenAI Agents SDK   | `ToolCallItem(name, input)`        | `name = tool_name; arguments = input`                       |
| LangChain           | `AgentAction(tool, tool_input)`    | `name = tool; arguments = tool_input`                       |
| Claude Code         | `tool_use` block (`name`, `input`) | `name = name; arguments = input; call_id = tool_use_id`     |
| OpenHands           | `Action(action, args)`             | `name = action; arguments = args`                           |

`arguments` SHOULD be a dict when the scaffold provides one. Some scaffolds (older LangChain) pass a free-form string — preserve as-is.

### 4.4 `tool_result` — environment → agent

```jsonc
{"output": <string|object>, "call_id": "optional-string", "error": "optional-string"}
```

`call_id` SHOULD match the corresponding `tool_call.call_id` when available. On scaffolds that don't surface call IDs, pair by step proximity (the tool_result immediately following a tool_call refers to that call).

### 4.5 `final_answer` — agent → environment (terminal)

```jsonc
{"text": "string"} | "string"
```

For single-string answers, either form is accepted — the verifier calls `str(content)`. Exactly one `final_answer` OR one `error` per trajectory (see §5).

### 4.6 `reward` — verifier → trace

```jsonc
{"reward": 1.0, "correct": true, "parsed": 4, "gold": 4, "verifier": "jordan_count"}
```

Emitted by the runner after the verifier scores the trajectory. Always the last event in a completed, verified trajectory.

### 4.7 `error` — any

```jsonc
{"type": "ExceptionClassName", "message": "string", "where": "optional-context"}
```

Terminates the trajectory. No `final_answer` is required after an `error`.

## 5. Trajectory compliance (MUST rules)

An adapter's output is protocol-compliant if and only if all of the following hold. Violations are detected by `agentanvil.schema.validate()`.

1. **Non-empty.** `events` has at least one entry.
2. **Initial observation.** The first event's `kind` is `observation`.
3. **Terminal event.** The last non-reward event is either `final_answer` or `error`. (`reward` appended by the runner does not count.)
4. **Single terminal.** At most one `final_answer` and at most one `error` per trajectory; not both.
5. **Contiguous steps.** `events[i].step == i` for all i.
6. **Non-decreasing timestamps.** `events[i].ts <= events[i+1].ts`.
7. **JSON-round-trip.** `json.loads(json.dumps(trajectory.to_json()))` equals the original.
8. **Tool-result pairing.** Every `tool_result` is preceded (possibly with `thought` in between) by a matching `tool_call` with the same `call_id`, OR — if call IDs are absent — by the most recent unpaired `tool_call`.

## 6. Extension: scaffold-specific richness

Adapters MAY attach anything under `meta` that helps debugging or advanced replay. Recommended keys:

| Key             | When to set                                         |
| --------------- | --------------------------------------------------- |
| `sdk_item`      | Concrete class name from the source SDK             |
| `latency_ms`    | Wall-clock latency of the step                      |
| `tokens_in`     | Input token count (if known)                        |
| `tokens_out`    | Output token count                                  |
| `cache_hit`     | Whether prompt cache hit (Anthropic)                |
| `subagent_id`   | For multi-agent systems, the sub-agent that emitted |
| `handoff_from`  | For handoff scaffolds, the previous agent           |

Consumers MUST ignore `meta` keys they don't recognize — never fail on unknown keys.

## 7. Version semantics

- **v0.1 (current)**: initial draft. Expect breaking changes before v1.0.
- **v0.x minor bumps**: additive only — new event kinds, new optional fields, new meta conventions.
- **v1.0**: first stable. Any breaking change after v1.0 requires a major bump and an explicit migration note in this document.

Adapters SHOULD stamp `meta.protocol_version` on the top-level trajectory.

## 8. What this protocol is not

- Not a checkpoint format. Replay is best-effort; faithful state recovery is a scaffold concern.
- Not a tool registry. Tool schemas live with the scaffold; this protocol only records calls.
- Not an RL reward function. Verifiers produce `reward` events; reward shaping and credit assignment are out of scope.
- Not a security boundary. Sandboxing is the runtime's job (OpenSandbox, the Rust supervisor, K8s policies). This protocol carries data, not enforcement.
