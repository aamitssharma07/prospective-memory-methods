# Batch-registration development diagnostic v1

Authored independently before live inference on these cases. The author did not
inspect PM-Bench inputs, the aborted prefix, or its model outputs for this task.
This is a generic development diagnostic, not an external held-out benchmark.
Known failure classes informed case design. Once outputs are inspected, any
subsequent tuning on these cases must be disclosed as development tuning.

Freeze `examples/batch_registration_v1.json` before the first scored run; preserve
its bytes/hash and all attempts. Do not change expected records to accommodate a
candidate. Five cases cover an eight-request bullet plan, shared weekday context,
two occurrences of one action, alternatives, multiline continuations, unchanged
restatements/speculation, and same-topic but distinct actions with revision and
cancellation. Expected source fragments are scorer-only and never model inputs.

Frozen case SHA-256:
`01a047af4dd6c329ff333f00ee31f482d6ddea40e458423c3945ffbfd184840f`.
There are 19 distinct requested obligations and 27 stage-record checks. No live
calls were made while authoring or validating this suite.

Every obligation has a rubric key, not a unique source-message ID: multiple
obligations deliberately share one original message. Maximum one-to-one matching
counts only records meeting all required source-fragment, separation, typed
clock/day/source, recurrence, status, provenance, and identity checks. One merged
record cannot count for several requests. Wrong or duplicate records incur FP;
unmatched required obligations incur FN. Missing registration cannot pass merely
because a later decision is silent. Shared header retention is checked separately
from typed weekday slots. Text fragments are bounded source-preservation tests,
not a semantic equivalence or trigger-understanding oracle.

Pre-inference representation rule: an empty permitted-day list and all seven
weekdays both mean unrestricted in the engine and score equivalently. Watch-source
sets remain exact for this deliberately strict registration diagnostic: an extra
available watched source fails the contract, but is not automatically proof that
the requested task's semantics are wrong. Every engine error, including a guard
event that repairs a proposed field, fails this gate; this is stricter than the
earlier protection-aware smoke diagnostic and errors remain separately reported.

Lifecycle stages ingest only public messages and snapshot the bank. Identity is
established from the first fully correct one-to-one match and must survive later
stages. A stage explicitly requesting no changes must preserve records exactly.
No trigger assessment, query execution, ACT, or success acknowledgement occurs.
Aggregate scores count stage-record obligations (including repeated lifecycle
checks); distinct initial request coverage is also reported separately.

Use the same Qwen3-8B BF16/nonthinking/temperature0 configuration as development
smoke tests, helper output4096, compact grammar preflight, timeout180seconds and
total request cap300. The harness supports v2 and v3 source-bound engines and
freezes the selected policy and dependencies before calling the model. Raw HTTP
responses, every helper call, stage snapshots, errors, token usage and latency
are retained in a fresh output directory; no overwrite. API/budget failures are
explicit aborts. Passing requires every stage and case, zero extra/wrong records,
all original messages retained, and zero engine/API errors. These are registration
scores, not PM-Bench F1, trigger accuracy, or demonstrated actor improvement.
