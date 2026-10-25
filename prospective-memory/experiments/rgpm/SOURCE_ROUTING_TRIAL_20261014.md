# Source-routing trial

Objective: improve GPT-5.4 performance over its no-memory baseline through a
plug-and-play memory helper. Actor controls execution; runtime sees public
instructions/observations only. No task IDs, benchmark labels, hidden state or
ground truth are used by this change.

The first isolated hypothesis follows GPT_FAILURE_REVIEW_20261014.md: choosing
sources separately from general registration reduces contamination from action
destinations and unrelated background text. New requests with validated verbatim
action/condition spans receive a small source-only call. It can alter only
watched_sources, using advertised capabilities; existing clock gates keep clock.
Revisions/cancellations use the existing compiler. Unknown, invalid or unsupported
routing retains the compiler output and emits a diagnostic event. This preserves
registration but does not guarantee its original sources were correct.

This is optional (--source-routing), default off. Actor/helper remain
GPT-5.4 / Qwen3-8B, max_tokens=768, temperature=0. No extra actor guidance,
legacy query handoff, query_budget=1, step_query_budget=2, no gate reporting,
and ACT verification off. Source routing is the sole candidate intervention;
trigger-readiness interpretation and CHECK scheduling are future ablations.

Offline preflight passed in preflight_source_routing_20261014, including 16
Experiment 3 regression tests. Tests cover unchanged non-source fields, rejected
unknown sources, unsupported/transport-failed routing, invalid extracted spans,
untouched revisions, multi-source/clock retention, raw call logging, and exact
snapshot/trajectory equivalence after checkpoint resume.

Live sequence: five generic helper-only routing diagnostics, then the existing
GPT smoke and smoke gate, then one full PMBench run only if all gates pass.
The launcher uses SOURCE_ROUTING=1 and writes full runs beneath
runs/source_routing_v1. Diagnostic responses and expected source sets are saved
separately; expected values never enter model requests. New model calls, raw and
parsed responses, costs, source changes, failures and checkpoints are recorded.

Comparison: baseline 75.71% F1 (53 TP / 6 FP / 28 FN), incumbent helper 74.65%
(53 / 8 / 28), failed verification variant 71.33% (51 / 11 / 30). Inspect
cross-day retrieval, non-clock on-time hits, source changes, and costs as well as
F1. Do not equate diagnostic success with benchmark improvement. These are
development trials on an inspected dataset; fresh baseline repeats and untouched
scenarios remain necessary for a robust improvement/generalization claim.

Submitted Slurm job: 1534704 (exp3-GPT-Qwen8-source-routing). Initial queue
state: PENDING / QOSMaxGRESPerUser while another user's-account GPU allocation
is active. Expected run ID: gpt-5-4-actor-helper-qwen3-8b-1534704. No live
diagnostic, smoke, or benchmark result exists at submission time.

Update: job 1534704 was canceled before starting at the user's request to batch
fixes and avoid GPT API spending. Accounting showed CANCELLED, Start None,
elapsed 00:00:00. No live diagnostics or GPT calls ran for this job. The next
steps are plan-only in [GPT_IMPROVEMENT_HANDOFF.md](GPT_IMPROVEMENT_HANDOFF.md);
the isolated trial sequence above is not authorization to resubmit.
