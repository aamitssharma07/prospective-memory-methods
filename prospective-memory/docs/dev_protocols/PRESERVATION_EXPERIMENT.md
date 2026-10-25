# Intention preservation and the next three-way experiment

Status: storage candidate and opt-in indexed extraction implemented; see the
results ledger for completed registration gates and their limitations.
This is opt-in research code, not a replacement for the current portable policy.
An exploratory PM-Bench integration is now available in `indexed_engine.py`:
42.2% Set-F1 vs fresh baseline 24.3%, but much worse recall and a major
output-count shift. No general memory improvement has been established. See
`INDEXED_PMBENCH.md` and the paired result report for details.

## What is implemented

`preservation.py` offers `PreservationBank` and `VerbatimExtractor`. It stores
every host instruction before inference, including messages that produce no
extraction or a model/transport error. Entries cite exact spans in immutable
original messages; there is no generated action/condition summary to overwrite
the source. Full original context is included in `view()`, including introductory
constraints outside a selected span. Scope comes from the host, not the model.
The extractor does not select observation sources; future adapters must expose
the host's actual sources rather than learning a restrictive source whitelist.

Registration is `accepted_unverified`, not semantically certified. The model can
still omit a request, merge unrelated requests, select an incomplete span, or
misclassify an update as a new request. Keeping the original message makes these
errors recoverable and inspectable; it does not automatically repair them.

Revisions and cancellations are staged. `resolve(proposal_id, target_id,
expected_revision, accept=True)` is a separate host operation. An accepted
revision appends the exact update, preserving the initial request and every
previous accepted update. Accepting cancellation changes lifecycle status.
Stale revisions and closed targets are rejected. The bank itself does not
automatically resolve targets; `IndexedMemoryEngine` now supplies an experimental
same-model resolver for its end-to-end run. A host resolver can be a policy or a person; this
API does not imply that manual target labels are available during evaluation.

Unresolved updates and unparsed messages are visible in `view()`. A downstream
actor must not treat pending entries alone as a resolved execution plan.
`receipts` describe the original ingestion outcome; proposal states describe
subsequent resolution. `snapshot()` / `restore()` preserve both without inference.
These features are wired into the PM-Bench runner only through the explicit
`--memory-policy indexed` candidate. The legacy policy and earlier run artifacts
are unchanged. The generic three-way actor ablation described below is still pending.

## Indexed extraction candidate

`indexed.py` provides `IndexedExtractor`, selectable with `--extractor indexed`.
The original verbatim extractor stays available and remains the CLI default.
Software assigns IDs and exact character offsets to nonempty sentence/line
units. The model makes one classification per unit, with the entire original
message and its indexed units visible. No previous bank or gold rubric is shown.

Each unit is labelled register, revise, cancel, continuation, context, fact or
uncertain. Operations anchor to themselves. Continuations link to the unit
starting the same request; software builds the exact contiguous source span.
Shared context remains in the full original message. This keeps bullet marks,
newlines and repeated text intact without asking the model to regenerate them.
Offsets disambiguate identical text occurrences; they do not perform semantic
deduplication. Existing quote-only callers still require a unique exact match.

Every ingestion receipt retains coverage units, classifications and errors,
including failed extraction. An empty/malformed response, unknown anchor, missing
classification, unresolved role or invalid continuation makes the message fail
atomically. Other units still receive their classification calls, but no partial
bank is silently advertised as complete. All original text remains recoverable.
The coverage audit survives snapshot/restore. Classification coverage only means
each unit was reviewed; a wrong fact/context label can still hide an intention.

Limits: at most 32 source units per message; one operation per unit; no
discontiguous request spans; mechanical segmentation can split abbreviations or
leave multiple semicolon-separated requests together. Cross-unit ambiguity can
block otherwise correct requests in the same message. One full-context call per
unit increases registration tokens and latency. This is not yet a general
language parser or an automatic update-target resolver.

## Linked multi-span candidate

`linked.py` / `--extractor linked` removes forced sentence boundaries from the
selection representation. Whitespace-delimited source tokens have IDs and exact
character offsets. A model returns inclusive token ranges, operation labels and
continuation links. Software requires those ranges to cover each source token
once in order and rejects gaps, overlap, unknown references and orphan links.
The complete original message remains available; the model never writes quotes.

One intention may now reference several nonadjacent original spans. In a bank
view, `source_fragments` contains each exact span and its offsets; `quote` is a
display/scoring projection joining them with newlines. It must not be described
as one contiguous quotation. Other tasks between the spans are not included.
Adjacent linked ranges merge using the original intervening whitespace.
Old single-span snapshots still restore and retain their previous scores.

This variant jointly groups clauses in one full-message call rather than one
independent call per sentence. It supports up to 256 source tokens and 32 ranges.
The model still decides where requests begin and which constraints belong to
them; complete token coverage is not semantic correctness. It can merge
requests, attach a clause incorrectly, or label a request as a fact. Unresolved
or structurally invalid coverage rejects the message without losing its text.
There is still no automatic existing-intention target resolver or PM-Bench wiring.

## Registration gate

```bash
python -m prospective_memory.evaluate_registration \
  --extractor indexed \
  --output prospective_memory/results/<new-run-name>
```

The server must already be running with whitespace-free structured decoding.
The runner snapshots code, cases and configuration, logs raw model calls, and
scores each request separately. Hand-authored source-fragment rubrics require
complete actions, every annotated condition, separation of unrelated requests,
correct operation and staged lifecycle. The labels never enter model input.
An incomplete/wrong proposal counts as both an FP and an FN. The gate requires
zero FP/FN/extraction errors and retention of all original inputs on this small
development suite. Passing would be a prerequisite, not a generalization claim.

This is source-coverage scoring, not semantic reasoning, resolved target accuracy,
trigger F1, execution success, or a comparison against PM-Bench's baseline.
Same-message context retention is mechanical and does not prove the actor uses it.

## Three-way comparison protocol (planned, not yet implemented/run)

Use one pinned Qwen3-8B BF16 server configuration, temperature 0 and thinking off.
Freeze generic streams, context-window policy, token limits and scoring rubrics
before inference. Freeze a fourth independent set for later evaluation; the
current development cases are not held out.

| Arm | Persistent memory available to the actor | Additional monitoring |
|---|---|---|
| Agent alone | Only ordinary host conversation/history | None |
| Agent + bank | Full lossless bank, with resolved update history | None |
| Agent + bank + selective monitoring | Same bank/context as the second arm | ACT/CHECK/WAIT evidence-backed proposals |

The two memory arms must replay **the same saved registrations and resolutions**
instead of independently recompiling them. Otherwise model variability confounds
the monitoring ablation. No oracle target assignment, pending-task labels,
hidden time, due-task lists or expected actions may enter any runtime arm.
The actor prompt and public history budget are common across arms; memory and
monitor text are explicit intervention tokens and must be counted separately.
Monitor-initiated queries are an intervention cost, not free observations.

Use the same host execution/acknowledgement interface in every arm. Score actual
actions against a predeclared semantic rubric (recipient/content/parameters,
timing and prerequisites), not merely ACT IDs or heuristic keyword overlap.
Report correct actions, misses, wrong actions and duplicates; separately report
false/missed reminders, query counts, calls, tokens and latency. Use repeated
runs and paired case outcomes; do not claim significance from one small trace.

Before launching: fix request separation/coverage, evaluate automatic update
target resolution including ambiguous cases, integrate the lossless view into
the monitor/host adapter, and implement the paired actor evaluator. If the bank
arm helps but selective monitoring does not, do not attribute the gain to
monitoring. PM-Bench comes after these generic gates.
