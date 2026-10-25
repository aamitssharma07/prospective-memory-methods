# Temporal and channel role development diagnostic

Authored on 2026-09-23 before any model use of these cases. Use
`examples/temporal_role_cases_v2.json` for the first live diagnostic.

Frozen SHA-256 values:

- Original v1: `4a99ad97c33d0488db9e59238365ebe5b1955cf34024388efcf4f118f08bcbf1`.
- Recommended v2: `e61d3953a810241ae9a3ea7e501fc85df8022ad93b310504b29492f53ffbae22`.

These are independently authored **development cases informed by a known failure
class**, not an external held-out benchmark. The author reviewed the existing
harness and trigger-role fixture format, but did not read PM-Bench data/results
or the new smoke-model outputs while constructing these cases. No model calls
were made. Future tuning after observing these results must be labeled as such.

## Pre-inference revision, with v1 preserved

V1 gave the first case an explicit approval timestamp of 14:10 for an action
scheduled at 16:35. That distinguishes the action time from a requirement that
approval occur *at* 16:35, but would also satisfy an invented requirement that
approval occur *before* 16:35. Root's review identified this weakness before any
model use. V1 remains unchanged as an audit artifact.

V2 changes only the first case's identifier and public approval evidence, plus
suite title/protocol text. Its earlier negative tick supplies no known approval;
the positive tick supplies current valid approval without an issuance timestamp.
The original request requires no approval deadline or fresh approval event.
Every original instruction and expected record/decision remains unchanged from
v1. Cases 2–4 are identical. This was design review, not adjustment to model
outputs or an altered scoring standard.

## Coverage

Each version has four cases, four separately supplied obligations, eight ticks
and eight decision rounds: four WAIT and four ACT. There are four initial record
checks and eight unchanged-pending checks, totaling 12. All four instruction IDs,
eight tick IDs and 12 observation IDs are unique within their respective sets.

| Case | Negative evidence | Positive evidence |
|---|---|---|
| Scheduled display lighting | Current time 16:34; approval unknown in v2 | Current time 16:35 and currently valid approval with no issuance time; display still unlit |
| Earlier inspection deadline | Cedar's inspection finished after 05:25, although its firing ends now | A different batch, Maple, was inspected before 05:25 and its firing ends now |
| Required event order | Indicator flashed before valve closure; both events occurred but in the wrong order | A fresh indicator flash occurs after the valve closed |
| Evidence versus delivery channel | `hatch_sensor` reports unlatched; `crew_chat` has no outgoing notification | Sensor reports latched; notification to Tavi through chat is still unperformed |

Only the first case has a structural action-time gate (`at 16:35`). The 05:25
cutoff belongs to a past prerequisite, not the action's execution time; it remains
in the source-bound semantic condition with `clock_op=none`. The order case is
also semantic: it requires a flash after closure, not an invented absolute clock
gate. The explicit cutoff and ordering requirements must not be erased while
avoiding invented chronology in the first case.

## Host and scoring contract

- Use the existing version-1 `evaluate_pis_grounded.py` JSON format and unchanged
  scorer. The filename v2 denotes a fixture revision, not a schema revision.
- Every tick supplies all required current observations explicitly. There are no
  pull-response fixtures and no expected CHECKs. Clock and named channels may be
  advertised as queryable, but their relevant snapshots are already supplied.
  An unexpected query cannot cause the runtime to invent evidence.
- Expected records/rounds are scorer-only. Public instructions, capabilities,
  source-bound records and current observations may enter model payloads; gold
  expectations must not. Retain each exact original instruction.
- A tick's evidence is the explicitly listed current set, not implicit replay of
  earlier observations. The pottery case uses two different batches under the
  explicit “for each” request; it does not revise one batch's inspection history.
- ACT is a reminder proposal, never evidence that its requested action happened.
  No actions are executed or acknowledged. All records remain pending and
  unchanged throughout each case. The different later indicator flash is real
  current evidence, not completion of the requested stamping action.
- Report exact case passes, registration/record checks, occurrence-aligned ACT
  precision/recall/F1, unexpected errors, protection events, calls/tokens and
  latency separately. Preserve every attempted run in a new output directory.
  Abort is not completion; do not change expectations to accommodate outputs.

## Limits and validation

This is an eight-decision diagnostic, not a statistical estimate or a PM-Bench
result. It does not evaluate actor uptake, polling, execution, scheduling latency,
long-memory retention, or successful completion. Explicit observation wording
keeps the cases unambiguous but may make them easier than natural environments.

The unchanged scorer checks required-source inclusion, not exact source equality;
it can therefore accept an unnecessary delivery-channel watcher in case 4. The
positive nevertheless requires the unperformed notification to become due from
the sensor state. Record lexical fragments are narrow preservation checks, not
semantic-equivalence proof. The pottery case does not directly score recurrence
metadata or repeat-completion lifecycle. Existing protection-event handling is
unchanged. Passing does not prove a projection contains no unsupported clause;
inspect projection text separately without retroactively changing labels.

`tests/test_temporal_role_cases.py` statically validates both hashes, existing
schema, counts/IDs, task-text-supported rubrics, positive/negative coverage, the
limited v1→v2 change, the semantic deadline/order controls, and explicit source
evidence with no fabricated query fixtures. These tests are not model-quality
evidence and do not call any model or engine callback.

Before live use, preserve the selected case file, this protocol, implementation
sources, model/decoding configuration and raw call logs. The current CLI supports
`--cases prospective_memory/examples/temporal_role_cases_v2.json`; this task adds
no engine, harness, scorer or runtime changes. Any later correction needs a new
version and an explicit explanation retaining the earlier artifacts.
