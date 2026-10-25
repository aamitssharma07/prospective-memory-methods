# V5: cached trigger interpretation, fair CHECKs and optional query handoff

Implemented opt-in policy: `pis_trigger_fair_v5`, class
[`SourceBoundFairTriggerEngine`](pis_fair_trigger.py). This describes the current
implementation, not a future observer/memo design or an authors' PIS reproduction.

Status at the September 23, 2026 launch handoff: full `candidate-v5-01` is running;
**no completed V5 PM-Bench score exists**. Runtime, adapter, runner and fixtures
are frozen during that run. Latest completed V3 result is 52.4390% set-F1 and
53.0864% recall. V5 must improve both in a complete audited comparison; a generic
plug-and-play benefit is not established.

## What happens, and which component does it

1. **Registration — helper LLM plus guarded code.** The inherited V3 compiler
   visits public layout units, classifies requests/updates and compiles typed
   metadata using advertised source names. Code copies exact source text; accepted
   revisions retain identity and chronological provenance. Updates/cancellations
   receive a same-obligation identity review. Visiting a unit does not guarantee
   correct semantic extraction. Original messages remain authoritative.
2. **Static projection — helper LLM, cached after accepted changes.**
   [`TriggerProjectionCache`](trigger_projection.py) derives
   `action_to_perform_next` and `readiness_question` for new/revised active records,
   in batches of four by default. For example, “release the crate” is the action;
   “is the scheduled time now, and is clearance present?” is the cue. This call
   receives no current observations. It neither establishes readiness nor executes
   anything. Unchanged views are reused, not regenerated on every observation.
3. **Current assessment — code then helper LLM.** On each host-supplied tick,
   pending, in-scope intentions pass through explicit weekday/clock gates. A hard
   `at` gate requires the same clock minute; `not_before` requires at least that
   minute. A missing required clock can propose a CHECK; an unsatisfied gate
   yields WAIT without a semantic assessment call. Time comes from public host
   evidence, not an implicit wall-clock tool. Unsupported/ambiguous hard gates
   may be removed by conservative registration guards while retaining the source
   condition for semantic interpretation.
4. **Readiness — one helper assessment per remaining eligible intention.** The
   helper answers `trigger_ready_now` using the cached view, original instructions
   and current observations. It must not require the future action to have already
   happened. Code maps local evidence references back to host IDs. ACT needs current
   watched-source evidence and no missing source; CHECK must name an advertised,
   queryable, watched source not already observed; otherwise WAIT. These checks
   constrain provenance, not whether the model's interpretation is logically right.
5. **Query allocation — deterministic source-level code.** All eligible intentions
   may propose CHECK before a shared slot is allocated. [`FairCheckArbiter`](fair_checks.py)
   groups by source, then favors the least recently offered/queried sources. Source
   names break ties; intention insertion order and many intentions watching the
   same source do not buy more slots. Only genuinely missing hard-clock dependencies
   receive priority. One representative CHECK per selected source reaches the host.
   Other requests become “shared/deferred; unresolved” WAITs, not “trigger false.”
6. **Choice and execution — main agent and host.** ACT is a reminder carrying the
   original source-bound action/condition and evidence, not a selected task handle.
   The main agent still resolves its current action menu and chooses what to do.
   The host authorizes/executes tools, returns observations and reports outcomes.

The actor and helper may use the same model checkpoint, as this experiment does;
registration, projection and assessment are helper call roles, not extra autonomous
agents. Cached interpretation does **not** cache truth: query replies can cause
another assessment cycle. This remains potentially expensive over a large bank;
there is no demonstrated 200-intention scaling guarantee or event-indexed shortcut.

## Host contract and PM-Bench handoff

A generic host supplies `Instruction(id, text, scope)`, stable-identity
`Observation(id, text, source, current)`, the available/queryable source registry,
and decision boundaries via `begin_step(step_id)`. Invoke `ingest` for public
instructions and `tick(observations, scope)` for current evidence. A push-only
source is not a tool. Mark buffered historical observations correctly: `current`
means usable in this decision, not proof that an event happened at the current time.

Record every actual query attempt with `record_query(source)`, including wrong or
repeated attempts; an offered CHECK is not an executed query or successful reply.
The configured proposal budget is one distinct source per assessment. Remaining
helper proposals also use `max(0, 2 - actual_attempts_this_step)` in this runner.
After two attempts the helper offers no more CHECKs and emits exhaustion guidance.
**Two is not a hard actor query cap**: the actor can ignore the advice. The separate
loop-safety guard aborts after more than 12 attempts without advancing; it does
not fabricate a successful action. A host requiring a hard tool limit must enforce
that in its own executor.

[`PMBenchAdapter`](adapters/pmbench.py) discovers channels from the public system
interface, treats `events` as visible/push-only, and strips action menus/handles
from helper evidence. Only the main agent sees and resolves those choices.
With `--memory-query-handoff explicit`, an existing validated CHECK additionally
produces an optional exact host action, for example:

```json
{"action":"query_state","choice":"NONE","task_ids":[],"channel":"advertised_source"}
```

The appendix also lists current observed sources and actual query attempts. The
placeholder above must be an actual advertised, watched, queryable source. This
formatting executes nothing, supplies no new evidence and permits the actor to
decline or choose something else. The default remains `legacy`; this mode must
be selected explicitly. Ordinary actor guidance displays ACT/CHECK, not the full
WAIT bank; silence is not evidence that a task is false or forbidden.

Only an authoritative host may call `acknowledge(id, "attempted"|"completed"|"failed")`.
A failed attempt returns to pending; completed recurring intentions return to
pending, while completed nonrecurring ones close. ACT delivery alone never
completes a record. **The current PM-Bench adapter logs actor choices but does not
infer completion or map chosen task handles into memory acknowledgments.** It
retains supported ACTs through within-step queries and clears that delivery cache
on choice/new step. Evidence-identity deduplication is not proof of execution.

## Opt-in reproduction

After the current frozen run finishes, use the recorded evaluation environment
and healthy actor/helper servers. Run from the repository root with a **fresh,
absent output path**; do not reuse the running `candidate-v5-01` directory:

```bash
.venv/bin/python pmbench_fallback_audit/run_memory.py \
  --mode selective --memory-version portable \
  --memory-policy pis_trigger_fair_v5 --memory-query-handoff explicit \
  --model Qwen/Qwen3-8B --memory-model Qwen/Qwen3-8B \
  --base-url http://127.0.0.1:30003/v1 \
  --memory-base-url http://127.0.0.1:30002/v1 \
  --memory-max-tokens 4096 --memory-check-budget 1 \
  --memory-projector-id 'Qwen/Qwen3-8B@b968826d9c46dd6066d109eabc6255188de91218;bf16;temperature=0;nonthinking;max_tokens=4096;vllm=0.8.5.post1;xgrammar=disable-any-whitespace' \
  --memory-projection-batch-size 4 \
  --scenario PMBench/data/synthetic_week_v9.json \
  --output pmbench_fallback_audit/memory_results/v5-reproduction-UNUSED
```

Replace the output name with a new attempt. This configuration uses BF16, no
quantization, temperature0/nonthinking, actor output768/helper4096, corrected empty
fallback, and no extra ACT verifier. The helper uses verified compact JSON grammar;
the actor uses its compatible backend on the separate endpoint. Do not skip the
helper grammar preflight to conceal decode failures. Exact server/environment
settings and launch sources are linked below, rather than inferred from port names.

`--memory-projector-id` is required: it must truthfully identify the helper
checkpoint and decoding/configuration. If these change, construct a new engine
with a new ID; the callback's effective model cannot be inferred by the cache.
For generic integration use `SourceBoundFairTriggerEngine(request, sources=...,
queryable_sources=..., query_budget=1, step_query_budget=2, projector_id=...,
projection_batch_size=4)`, where `request(system, payload, schema)` owns inference
transport and raw-response logging. Helper-only harnesses use `--policy
pis_trigger_fair_v5`, `--projector-id` and `--projection-batch-size`; those scripted
hosts do not measure uptake of the PM-Bench explicit handoff.

## Cache, persistence and failures

Cache bindings include the complete intention, original chronological messages,
revision/status, caller projector ID and a prompt/schema fingerprint. The final
launch definition SHA-256 is
`bc75291de7765acac0c75c069b14d37777571d8b39f8a89e0d7847baa61561d6`.
Missing/stale/unsupported/error views use the inherited V3 assessment; ticks never
retry projection. Unchanged unsupported/error entries are cached too: invalidate
explicitly before retrying. Authoritative pending/attempted status transitions can
rebind identical static meaning without inference; closure or other source/meaning
changes invalidate it. Batch size is a row cap, **not** a token budget, and 800-character
derived fields do not prove complete or faithful interpretation.

Engine snapshots preserve the bank, original instructions, query/deduplication
state, projections, assessor fingerprint and fair offer/query histories. Restore
validates on temporary state before committing; incompatible policy, projector,
prompt/schema, source binding or malformed histories are rejected. The cache
restores its saved batch size, so reproduction/audit also checks it against the
manifest. Changing queryable capabilities resets fair history with a logged event.
Host permissions must still be validated, not granted just because a snapshot says
a source exists. PM-Bench adapter snapshots additionally preserve conversation
prefix/cursor, evidence IDs, ACT cache and handoff mode; engine-only state is not
enough to resume that adapter. A changed/truncated conversation requires a fresh adapter.

Offline reporters reconstruct historical projection definitions from recorded
prompt/schema data, validate fingerprints and use a no-callback matching class;
they do not execute historical frozen Python or relax runtime restore checks.
Source-binding errors are visible failures, not evidence of success: invalid
registration/source/update identity may reject a change; malformed projection
identity/provenance produces an error/fallback; invalid current-evidence references
can produce logged `pis_decide` errors and unresolved WAITs. Inspect the error and
arbitration logs, not only transport success or aggregate scores.

## Evidence, costs and known limits

Final-source helper checks are smoke03 10/10, transfer02 10/10, trigger-role01 8/8,
temporal-v2-01 4/4, and **batch01 4/5 strict FAIL**. Batch has 18/19 fully correct
initial records and stage26TP/1FP/1FN: an extra available clock watcher remains on
one visible-event intention. It can affect query allocation or evidence/deduplication
and is not assumed harmless. Full launch uses a narrow predeclared exploratory
exception, not a relabelled 5/5 pass. Separate semantic inspection found `repeat=false`
for “for each pottery batch”; the temporal rubric does not exercise that recurrence
slot or a later batch after completion, so 4/4 does not establish lifecycle correctness.

Smoke01/02 failures and the earlier-prompt transfer01 remain preserved. All final
preflights are development-tuned, not held-out/generalization evidence. Scripted
506-core/53-runner checks establish engineering contracts, not semantic accuracy.
Final smoke alone costs 57 calls including preflight, 57,147 helper tokens and
76.15 seconds; this is neither full-run cost nor isolated projection overhead.
Registration adds layout-unit calls; projection adds changed-record batch calls;
assessment still scales with eligible intentions and observation cycles. Fairness
is a coverage heuristic, not optimal query value; persistent hard-clock priority
can starve other sources. No future observer memo, standalone sentence splitter,
partial-WAIT formatter or general scalability guarantee is part of V5.

Evidence and exact reproduction records:

- [Final preflight audit, costs and limitations](../results/pis_trigger_fair_v5_preflight_20260923_01/README.md).
- [Preserved failed/earlier-prompt attempts](../results/pis_trigger_fair_v5_development_20260923_01/README.md).
- [Launch decision and frozen configuration](../pmbench_fallback_audit/memory_results/qwen3-8b-pis-source-bound-pair-20260922-01/LAUNCH_DECISION_V5_01.md).
- [Exact protocol/command and reporting targets](../pmbench_fallback_audit/memory_results/qwen3-8b-pis-source-bound-pair-20260922-01/PROTOCOL_NEXT_V5.md).
- [Historical launch identity; reverify before process control](../pmbench_fallback_audit/memory_results/qwen3-8b-pis-source-bound-pair-20260922-01/LAUNCH_IDENTITY_V5_01.json).
