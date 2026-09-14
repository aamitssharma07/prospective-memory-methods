# Portable prospective memory

An environment-independent memory component for **unrelated intentions with
arbitrary future conditions**, rather than a task sequence or a shared goal.
PM-Bench is one evaluation adapter; its task IDs, menus, scoring rules, and hidden
state are not inputs to the generic core or language-model policy.

Status: implemented and tested with scripted providers. No live-model result or
improved prospective-memory accuracy is established for this version yet.
Requires Python 3.10+; core, policies, demo, and tests use the standard library.

## What is different from the previous reminder bank?

- `core.py` owns stable IDs, instruction provenance, revisions, cancellation,
  execution acknowledgements, persistence, evidence identities, and query limits.
- `llm.py` separates intention registration from condition assessment. A host
  supplies a model callback; neither the model provider nor benchmark is baked in.
- `adapters/pmbench.py` translates the benchmark's public conversation. Menus and
  A/B/C choices cannot become registration input or trigger evidence. Only the
  actor sees the menu and resolves an action description to its current handle.
- The interface distinguishes **ACT**, **CHECK**, and **WAIT**. Missing information
  is a reason to request an observation, not evidence that an action is due.

The compiler still interprets natural language. A quote validates provenance,
not whether a proposed intention or revision is semantically correct. The
assessor still decides whether all trigger conditions hold. This is a reusable
architecture with safeguards, not a symbolic proof system or a solved general
prospective-memory model.

## Host interface

```python
from prospective_memory import Engine, Instruction, Observation
from prospective_memory.llm import LLMMemoryPolicy

# Your callback performs inference and returns a decoded dictionary matching
# the supplied JSON Schema: request(system: str, payload: dict, schema: dict).
policy = LLMMemoryPolicy(request)
memory = Engine(
    policy.compile, policy.assess,
    sources=("incoming_messages", "experiment_status", "clock"),
    queryable_sources=("experiment_status", "clock"),
    query_budget=1,
)

memory.ingest(Instruction(
    "user-request-1", "When the experiment finishes, summarize its results."
))
decisions = memory.tick([
    Observation("experiment-event-42", "Experiment finished successfully.",
                source="experiment_status")
])
```

The host handles decisions:

| Decision | Meaning | Host responsibility |
|---|---|---|
| ACT | The assessor proposes the stored action, with current evidence IDs. | Verify/authorize the action, execute if appropriate, report outcome. |
| CHECK | Evidence is missing and an advertised pull source may supply it. | Query that source and pass its actual response to another `tick`. |
| WAIT | No supported intervention to deliver. | Continue ordinary work; deliver later observations. |

An ACT is a proposal, not a successful execution. Use
`memory.acknowledge(id, "attempted")`, then `"completed"` or `"failed"` based on
actual host feedback. Completion closes a one-shot intention; recurring
intentions rearm. Failure permits retry. Cancellation/revision requires a new
explicit instruction with a supporting quote and the existing software ID.

Use `memory.snapshot()` and `memory.restore(state)` for JSON-compatible state.
The model callbacks are injected again when creating the engine, not serialized.
For PM-Bench, use the adapter's snapshot/restore instead: its conversation prefix,
cursor, scope, current observations, and outstanding ACT guidance also matter.
The host must separately preserve its session/execution state. The runner saves
the last adapter snapshot, but has no simulator-resume command yet.

## Observation and monitoring contract

- Sources come from the host's capabilities, not a task/channel lookup table.
  Explicitly specify `queryable_sources` to separate push streams from pull
  tools. Omitting it makes all advertised sources queryable for simple hosts.
- The host invokes `tick` on incoming events or its own timer. There is no
  autonomous background process, scheduler, or guaranteed observation frequency
  in this package. A CHECK alone does not perform an environment read.
- The query budget limits distinct emitted CHECK sources **per tick**, not total
  queries over a session. Multiple intentions can share a source response.
  A host needing a global cost bound must enforce it across ticks and actors.
- Deliver stable observation IDs. Reusing an ID with different text/source is
  rejected. Mark historical/irrelevant evidence `current=False`; only evidence
  present in the current call can support ACT. Keep still-relevant evidence in
  successive calls when conditions require multiple observations.
- `current=True` does not prove an event happened now. Provide timestamps and
  scope where timing matters; buffered events need careful handling. The module
  never reads a simulator's true time or due-task labels.
- Deduplication tracks cited evidence from intention sources within a revision.
  Extra context from another source cannot disguise reused evidence. New IDs for
  the same real event, or unrelated new evidence from a registered source, are
  not semantically deduplicated; accurate event identity remains a host duty.
- An intention with no suitable source can be preserved with `sources=()` but
  cannot ACT or CHECK. Supplying a suitable source later requires an explicit
  policy/registration update; capability discovery alone does not rewrite it.
- Scopes are optional host-defined strings. Empty or `*` applies across scopes;
  otherwise a `tick` matches that scope exactly. No task sequence is required.

## PM-Bench integration

The adapter discovers channels from the public system prompt, registers candidate
instruction prose, and assesses visible narration and ordinary channel replies.
It does not receive scenario objects, hidden state, task labels, or scorer output.
Public narration/tool replies can contain instructions as well as facts; the
compiler must distinguish these. Menu stripping does not solve that semantic task.

CHECK is passed to the actor as an ordinary `query_state` recommendation, so
actual benchmark queries are counted. The actor can ignore it or make additional
queries. ACT reminders survive unrelated within-step queries while their cited
evidence and intention remain valid. New steps discard prior current observations.
This conservative step boundary can discard useful long-lived state; the generic
engine allows hosts to use a richer evidence-retention policy.

The benchmark provides no public semantic success signal for selected task
handles. This adapter therefore logs choose attempts but **does not automatically
acknowledge completion or map paraphrased actions onto handles**. One-shot records
can remain pending and remind again on new evidence. This lifecycle limitation
must be addressed with public, verifiable feedback before claiming end-to-end
execution reliability; hidden scorer success must not be used as runtime feedback.

With an already running compatible local model server:

```bash
.venv/bin/python pmbench_fallback_audit/run_memory.py \
  --mode selective --memory-version portable \
  --model Qwen/Qwen3-8B --memory-model Qwen/Qwen3-8B \
  --base-url http://127.0.0.1:30002/v1 \
  --memory-max-tokens 4096 --memory-check-budget 1 \
  --output pmbench_fallback_audit/memory_results/qwen3-8b-portable-01
```

Portable currently supports selective mode only. Existing v1/v2 and baseline
paths remain available. All use empty actor fallback. The new command has not
been run with a live model as part of this implementation. The 4096 helper-token
allowance is an explicit proposed configuration, not the 2048 used in earlier
pilots; report inference cost/configuration differences in any comparison.

## Validation and next experiment

```bash
python3 -m unittest discover -s tests -p 'test*.py' -v
python3 -m unittest discover -s pmbench_fallback_audit -p 'test*.py' -v
python3 -m prospective_memory.demo --output prospective_memory/examples/event_stream_results.json
```

The independent demo covers delays, unrelated/simultaneous intentions, cancelled
and revised requests, absent triggers, stale/invented evidence, push/pull queries,
persistence, and recurrence. Its compiler/matcher are deterministic fixtures,
not a language model. See [the report](examples/event_stream_results.json) and
[verification notes](examples/VERIFICATION.md).

Next: validate the actual model on held-out, free-form event streams with
paraphrases, negation, ambiguous timing, irrelevant distractors, and conjunctions;
then run the unchanged generic policy through PM-Bench. Report trigger recall,
false alarms, execution success, detection delay, queries and helper/actor tokens
separately. Keep the model/prompt fixed across environments and do not tune
task-specific rules against the benchmark test trace.

The current prototype scans the active bank and retains full provenance and
observation history. Bounded retention, scalable retrieval, scheduling policies,
and a model-cost-matched comparison remain future work.
