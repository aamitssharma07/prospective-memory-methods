# Portable prospective memory

## Opt-in evidence-first refinement: first live smoke gate failed

`--memory-policy pis_grounded` adds a source-grounded hard-clock guard, a separate
review of proposed memory changes, and evidence-state assessment mapped by code
to WAIT/CHECK/ACT. It addresses observed invented clocks and contradictory CHECK
outputs without treating free-text reasoning as authorization to act. Existing
policies/defaults and frozen baseline results remain unchanged. See
[design, trace diagnosis, usage and limitations](PIS_GROUNDED.md).

The first Qwen3-8B live smoke completed: 0/10 full case contracts, 6/11 required
origins registered, 4 ACT proposals but no CHECK. All seven accepted records have
incomplete actions; one ACT is a duplicate caused by a revision becoming a new
record. Cancellation/paraphrase/unavailable-tool behavior had partial successes,
but action quality still fails. This is not a PM-Bench result. Do not promote or
launch the full week from this gate. [Report and all cases](../results/pis_grounded_smoke_20260922/README.md).
Both GPUs released; 210 software tests pass, which does not imply model competence.

## Latest comparison: actual author PIS versus our implementation

On the 80-step Qwen3-8B PM-Bench week, the actual pinned GitHub PIS scored 32.9%
Set-F1 (46 TP / 153 FP / 35 FN), versus 42.9% for our prior independent PIS-inspired run
(62/146/19), and 24.3% for a fresh baseline. This is a single local comparison,
not paper-exact reproduction or cost-matched proof of a general memory benefit.
Our prior module emitted no ACT proposals and invoked no verifier.
See [results and caveats](../pmbench_fallback_audit/memory_results/qwen3-8b-author-pis-20260922-01/RESULTS.md),
[trace-backed failure examples](../pmbench_fallback_audit/memory_results/qwen3-8b-author-pis-20260922-01/FAILURE_CASES.md),
and [author reproduction protocol](../pmbench_fallback_audit/AUTHOR_PIS_EXPERIMENT.md).

## New opt-in candidate: PIS-inspired typed memory

`pis.py` adds Form/Revise slot filling, weekday/clock eligibility filtering,
per-intention language judgments and host-step query budgeting. `pis_verified`
adds an original-instruction verifier; the completed pilot did not exercise it.
Both are available through `run_memory.py --memory-version portable --mode
selective --memory-policy pis` (or `pis_verified`). Defaults remain unchanged.
See [three-arm protocol and limitations](PIS_EXPERIMENT.md). This is independent
paper-inspired work, not an exact reproduction or a validated improvement.

Generic hosts should call `begin_step(stable_id)` at each new decision and
`record_query(source)` for actual query attempts, including wrong/repeated ones.
Supply `exhausted_query_guidance()` to the actor after its step budget runs out.
Suggestions never imply successful execution: use `acknowledge` with actual host
feedback. The PM-Bench adapter supplies the step/query callbacks but has no
authoritative completion feedback. More than 12 query attempts in one step
aborts the pilot explicitly instead of inventing a forced choice or score.

## Earlier: exploratory PM-Bench indexed-memory run

An end-to-end indexed bank/resolver/monitor is available via the portable runner's
`--memory-policy indexed`. On a fresh matched Qwen3-8B pair it scored **42.2%
Set-F1 vs baseline 24.3%**, but recall fell from 96.3% to 42.0%. The candidate
selected exactly one task per step; baseline selected 3–8. This is not established
evidence of better remembering. Seventeen helper outputs truncated and three daily
plans failed registration. No defaults changed; both GPUs released after the run.
See [integration/limitations](INDEXED_PMBENCH.md) and
[full paired results](../pmbench_fallback_audit/memory_results/qwen3-8b-indexed-pair-memory-20260921-01/RESULTS.md).

## Earlier: source-indexed and multi-span registration

Two new opt-in registration extractors: `indexed` reviews each sentence/line
unit; `linked` groups word-indexed source ranges, including discontiguous clauses.
Use `python -m prospective_memory.evaluate_registration --extractor indexed
--output <new-directory>` (or `linked`). Existing policy defaults are unchanged.

On the reused nine-case registration suite, verbatim control scored 59.3% F1,
indexed 88.2%, and linked 46.2%. Additional development challenges exposed failure
to preserve complete clause groupings (indexed 0%, linked 54.5%). No gate passed;
no end-to-end or PM-Bench improvement established. See
[results and limitations](results/INDEXED_REGISTRATION_20260921.md) and
[representation/protocol](PRESERVATION_EXPERIMENT.md).

## Earlier: lossless bank and separate registration gate

`preservation.py` is a new opt-in storage candidate: originals survive failed
extraction, updates append exact history, and uncertain mutations remain staged
for host resolution. It does not replace the legacy engine or PM-Bench policy.
Its nine-case Qwen3-8B registration gate failed (8 TP / 3 FP / 8 FN; 59.3% F1),
despite retaining all 13 original input messages. This is source-coverage scoring,
not trigger F1 or evidence of improved agent performance. The planned three-way
comparison was not launched. See [design and protocol](PRESERVATION_EXPERIMENT.md)
and [run report](results/qwen3-8b-preservation-registration-20260921-01/RESULTS.md).

## September 21 generic repairs

**Experimental, not promoted.** The latest isolated compiler passed the two
incremental-registration regressions but scored 61.5% F1 on the broader seven-case
development suite versus legacy's 77.8%. The earlier candidate's PM-Bench run
was inert and did not improve the fresh baseline. Keep `legacy` as the default;
the new modes are research candidates, not a validated replacement.
See `results/GENERIC_REPAIRS_20260921.md` for all iterations and limitations.

`grounded.py` adds opt-in policies without changing the historical `legacy`
policy. Both independent evaluation (`--policy`) and the portable PM-Bench
runner (`--memory-policy`) accept `legacy`, `grounded`, and `verified`.

- `grounded`: registration cites software-assigned source-line IDs. The host
  reconstructs exact contiguous source text, so the model need not reproduce
  whitespace or concatenate quotations. Each explicit list item gets a separate
  call with the whole message available as context. Revision/cancellation
  instructions distinguish a change in the plan from occurrence of its trigger.
  New requests are extracted without the existing bank, so unrelated stored tasks
  cannot interfere with extraction. Only revisions/cancellations make a second
  call to resolve the existing target and preserve unchanged constraints. The
  resolution schema cannot change the extracted operation into another one.
- `verified`: adds a separate same-model assessment of each proposed ACT using
  the intention, provenance and current permitted evidence. It does not see the
  proposing model's reason. An unsupported verdict becomes explicit WAIT; valid
  ACTs still pass the core's evidence and duplicate checks. Verification calls
  are logged as `phase=verify` and count toward reported token use.

These are semantic model decisions, not proofs. Verification can reject correct
actions or agree with an incorrect proposal. The verifier cannot recover a
proposal the assessor never made, or a missing registration. Line splitting
handles explicit lists; it is not a complete natural-language request parser.
Registration supports at most 128 nonempty lines per message and fails explicitly
above that limit. Multiple operations in a message refer to the bank as it stood
before that message, so a revision of an intention first introduced in the same
message is not supported. No automatic execution acknowledgement or benchmark
ground-truth access has been added. All pending in-scope intentions are still
assessed; large-bank retrieval remains future work.

`examples/semantic_cases_v2.json` contains fresh regression cases authored around
observed failure categories before live evaluation. This is a development test,
not an independently held-out generalization benchmark. Freeze cases and prompts
before running the comparison; do not tune against a PM-Bench test trace.

Example diagnostic (with the whitespace-free helper server running):

```bash
.venv/bin/python -m prospective_memory.evaluate \
  --cases prospective_memory/examples/semantic_cases_v2.json \
  --policy verified --output prospective_memory/results/verified-fresh-01
```

For PM-Bench add `--memory-policy verified` to the portable command below. Run
the actor on its own `auto` grammar server and provide its URL with `--base-url`;
set `--memory-base-url` to the whitespace-free helper server. Use that same actor
server and weight revision for a fresh baseline (`--mode baseline`, leaving
`--memory-version` at its default), with the same empty fallback and token cap.

An environment-independent memory component for **unrelated intentions with
arbitrary future conditions**, rather than a task sequence or a shared goal.
PM-Bench is one evaluation adapter; its task IDs, menus, scoring rules, and hidden
state are not inputs to the generic core or language-model policy.

Status: live-tested, with no established general performance improvement.
September 18's legacy portable run scored 42.5% on PM-Bench; the September 21
experimental candidates and matched baseline are described above and in
`context/results_ledger.md`. Scores from different diagnostic sets are not comparable.
Requires Python 3.10+; core, policies, demo, and tests use the standard library.

## What is different from the previous reminder bank?

- `core.py` owns stable IDs, instruction provenance, revisions, cancellation,
  execution acknowledgements, persistence, evidence identities, and query limits.
  It calls the matcher as `matcher(intentions, observations, sources,
  queryable_sources)`, so the assessor is told which sources it may actually
  CHECK rather than guessing and having the proposal rejected.
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

## Structured-output requirement

A JSON grammar permits unbounded whitespace between tokens. With greedy decoding
a model can settle on a separator fixed point once a field is complete and emit
newlines until the output cap, so a finished answer is discarded as a decode
error and reads downstream as deliberate silence. Start the server with:

```bash
--guided-decoding-backend 'xgrammar:disable-any-whitespace'
```

The equivalent per-request field reaches only vLLM's V0 engine; V1 builds a
single backend from server config and strips per-request options. Both
`prospective_memory/evaluate.py` and `pmbench_fallback_audit/run_memory.py`
probe the live server before starting and refuse to run without this guarantee,
unless `--allow-grammar-whitespace` is passed. `prospective_memory/decoding.py`
holds the shared probe.

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

Start the helper server with `python -m prospective_memory.serve ...` (it sets
the whitespace-free grammar). The PM-Bench actor's own schema is rejected by
xgrammar, so run the actor on a second, default-backend server and pass it as
`--base-url`, with the helper server as `--memory-base-url`:

```bash
.venv/bin/python pmbench_fallback_audit/run_memory.py \
  --mode selective --memory-version portable \
  --model Qwen/Qwen3-8B --memory-model Qwen/Qwen3-8B \
  --base-url http://127.0.0.1:30003/v1 --memory-base-url http://127.0.0.1:30002/v1 \
  --memory-max-tokens 1024 --memory-check-budget 1 \
  --output pmbench_fallback_audit/memory_results/qwen3-8b-portable-01
```

Portable currently supports selective mode only. Existing v1/v2 and baseline
paths remain available. All use empty actor fallback. This command produced
`pmbench_fallback_audit/memory_results/qwen3-8b-portable-20260918-02`; the 1024
helper cap matches the diagnostic's compile cap and replaces the earlier 4096
proposal, which predates compact output. Report configuration differences in
any comparison.

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
