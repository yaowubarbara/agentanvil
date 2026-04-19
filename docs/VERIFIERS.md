# Verifier & Evaluator Guide

AgentAnvil separates **verification** (did the agent get the right answer?)
from **evaluation** (how well did they do it?). Both are first-class.

## Verifiers vs Evaluators

| | Verifier | Evaluator |
|---|---|---|
| **Question** | "Is the answer correct?" | "What else should we measure?" |
| **Output** | Single `VerifyResult` (correct + reward + parsed + gold) | Zero or more `EvalScore` objects |
| **Cost** | Usually cheap (string compare, execution) | Can be cheap (regex) or expensive (LLM judge) |
| **When it runs** | Always, per trajectory, emits REWARD event | Opt-in, via `EvaluatorRegistry` |
| **RL reward source** | Yes, directly | Usually no (metrics only) |

A trajectory's canonical reward comes from the verifier. Evaluators attach
richer annotations but are not the RL signal.

## Shipped verifiers

| Verifier | Task shape | Scoring | Pairs with pack |
|---|---|---|---|
| `JordanCountVerifier` | Image + dots + curve | Strict ANSWER parser, binary | `jordan-count-mini` |
| `GSM8KVerifier` | Grade-school math word problem | `#### N` parser, binary with numeric tolerance | `gsm8k-mini`, `simple-qa-mini` |
| `HumanEvalVerifier` | Function completion | Subprocess execution of `check()`, binary | `humaneval-mini` |
| `SWEBenchLiteVerifier` | GitHub issue → patch | Lightweight patch-overlap score (binary or scalar) | `swe-bench-micro` |

### Strict parsing contract

Every verifier declares a parse contract and **never heuristically salvages**
non-conforming output. If the model produced narrative text instead of the
requested format, parsed is `None` and `correct=False`.

**Why strict matters for RL:** a reward function that rewards "kind of right"
outputs teaches the model that format compliance is optional. We want sharp,
binary signal.

## Shipped evaluators

Programmatic (free):
- `ContainsKeywordsEvaluator` — required keywords appear
- `RegexEvaluator` — pattern match
- `LengthBandEvaluator` — `len(answer) ∈ [min, max]`
- `NoForbiddenWordsEvaluator` — safety keyword filter
- `TrajectoryShapeEvaluator` — required event kinds / tool-call count bounds

Composite:
- `RubricEvaluator` — weighted sum over programmatic criteria
- `EvaluatorRegistry` — run many in one pass

LLM-based (costs API calls):
- `LLMJudgeEvaluator` — Claude / OpenAI judge on 1-5 scale, strict score parse

## Writing a new verifier

```python
from dataclasses import dataclass
from agentanvil.verifier.base import Verifier, VerifyResult

@dataclass
class MyTask:
    task_id: str
    prompt: str
    gold: str

    def initial_observation(self) -> dict:
        return {"text": self.prompt}

class MyVerifier(Verifier):
    name = "my_bench"

    def verify(self, final_answer: str, task: MyTask) -> VerifyResult:
        parsed = self._parse(final_answer)
        correct = parsed == task.gold
        return VerifyResult(
            correct=correct,
            reward=1.0 if correct else 0.0,
            parsed=parsed,
            gold=task.gold,
            meta={"parse_failed": parsed is None},
        )

    def _parse(self, output: str):
        # strict parser — never heuristically salvage
        ...
```

Then bundle into a task pack under `agentanvil/packs/my_bench/`:

```
my_bench/
├── pack.yaml          # name, verifier dotted path, task_class, version, license
└── tasks.jsonl        # one task per line
```

## Writing a new evaluator

```python
from agentanvil.evaluator import Evaluator, EvalScore

class MyEvaluator(Evaluator):
    name = "my_metric"

    def score(self, final_answer: str, task=None, trajectory=None) -> EvalScore:
        value = self._compute(final_answer)
        return EvalScore(
            name=self.name,
            value=value,
            label="pass" if value > 0.5 else "fail",
            meta={...},
        )
```

Register with an `EvaluatorRegistry`:

```python
from agentanvil.evaluator import EvaluatorRegistry

reg = EvaluatorRegistry()
reg.add(MyEvaluator())
reg.add(RegexEvaluator(r"ANSWER:\s*\d+", name="has_format"))
scores = reg.run(final_answer, task=task, trajectory=traj)
# scores = {"my_metric": EvalScore(...), "has_format": EvalScore(...)}
```

## LLM-as-judge best practices

1. **Use a smaller model for judging.** The judge doesn't need to solve the
   task — it needs to score with consistency. Default to Haiku / gpt-5-nano.
2. **Strict score parsing.** Our `LLMJudgeEvaluator` requires `SCORE: N` on
   its own line; judge outputs that ramble score 0 with `label="parse_fail"`.
3. **Inject the gold answer when known.** The judge's job is easier with a
   reference; the prompt template does this automatically for tasks with
   `.gold_answer` or `.gold_count`.
4. **Log the reasoning.** `EvalScore.reasoning` captures the judge's one-line
   rationale — invaluable for finding systematic judge biases.
5. **Budget per run.** Estimate: 200 input + 40 output tokens per judgment.
   Judging 40 tasks with Haiku ≈ $0.02.

## See also

- [ADAPTERS.md](ADAPTERS.md) — how adapters produce the trajectory that verifiers score
- [TRAJECTORY_PROTOCOL.md](TRAJECTORY_PROTOCOL.md) — where REWARD events live
- [../agentanvil/verifier/jordan_count.py](../agentanvil/verifier/jordan_count.py) — reference verifier
- [../agentanvil/evaluator.py](../agentanvil/evaluator.py) — evaluator framework
