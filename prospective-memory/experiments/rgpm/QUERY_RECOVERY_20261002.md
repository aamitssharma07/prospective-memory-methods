# Query-limit recovery

Run 1503127 failed after 58 committed steps when the actor repeatedly queried
the clock on Friday. Its artifacts remain available; it has no final benchmark
score and must not be compared as a complete run.

The Experiment 3 runner now intercepts the next actor request after 12 state
queries in a step and uses the existing invalid-response empty fallback.
The trajectory records fallback_triggered and the actor_query_limit reason;
events.jsonl records the step and all query channels. All actual model calls,
raw responses, token usage and durations remain in the normal call artifacts.
No extra model response is fabricated. Strict scoring treats the fallback as
incorrect, including steps with an empty expected answer.

The policy is recorded in the manifest and source fingerprint. Changed-code
runs use new directories; they cannot resume the old run under a new policy.
Shared PIS and benchmark code are unchanged by this fix.

Offline preflight passed in preflight_query_recovery_20261002. The added test
forces clock-query loops across four steps, interrupts after a checkpoint,
resumes, and verifies 48 preserved actor calls, four failure events, empty
actions, and zero exact-match credit.

Actor and helper: Qwen/Qwen3-8B. Both use max_tokens=768.

- Live smoke: Slurm 1503139, run ID qwen3-8b-1503139.
- Full benchmark: Slurm 1503140, run ID qwen3-8b-1503140.
- Full job depends on afterok:1503139 with kill-on-invalid-dep enabled.

This change improves run completion and failure attribution. It does not
establish an F1 improvement; that requires the completed benchmark results.
