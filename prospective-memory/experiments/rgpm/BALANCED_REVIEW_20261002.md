# Balanced actor guidance candidate

Compared saved per_task.csv, trajectory.jsonl and actor calls from Qwen3-8B
runs 1503009, 1503073 and 1503118 on synthetic_week_v9. All have 80 steps.
These are development results on an inspected dataset, not held-out evidence.

| Run | Set F1 | Routine hits / 28 | Irregular hits / 53 | Event hits / 57 | Time hits / 24 |
| --- | --- | --- | --- | --- | --- |
| 1503009 | .5269 | 27 | 17 | 25 | 19 |
| 1503073 | .2885 | 26 | 47 | 51 | 22 |
| 1503118 | .4472 | 19 | 17 | 22 | 14 |

Irregular and time denominators exclude two canceled tasks. Categories overlap.
The latest run loses 14 earlier hits and gains six, for a net loss of eight.
The entire net loss is routine tasks; irregular hits remain 17, though their
identities differ. Updated tasks remain two hits and seven misses. The large
reduction in query counts correlates with the regression but does not establish
causation: helper prompt changes and actor guidance are confounded across runs.

Concrete trace: 1503118 calls.jsonl, actor request at Monday/d1_s1 contains a
WAIT explanation that rejects breakfast because dinner is not confirmed, despite
describing the trigger as breakfast OR dinner. The actor omits breakfast and
selects the 11:00 medication without querying the clock. The helper proposed
CHECK clock; the saved trajectory records zero queries. This establishes both
an erroneous helper explanation and failure to follow its information request.
It does not establish that removing WAIT alone fixes either behavior.

Candidate balanced_v2 changes only Experiment 3 actor guidance: omit verbose
WAIT explanations, retain ACT/CHECK and explicit query handoff, encourage
budgeted evidence gathering and independent recurring occurrences. Keep exact
action matching and the distinction between menu availability and readiness.
WAIT decisions and reasons remain in saved memory traces for diagnosis.
Helper prompts, models, query budgets and max_tokens=768 stay fixed for this
comparison with 1503118. Preflight now includes adapter tests as well as runner
tests, fixing an omission in the earlier preflight.

Validate offline, then live smoke with Qwen3-8B as actor and helper. Inspect
semantic outcomes as well as the smoke health gate. The six-step smoke is an
execution check and lacks routine multi-occurrence coverage; it cannot select
the winning methodology. Retain 1503009 as best observed candidate until a new
full run demonstrates improvement. Assess TP/FP/FN, routine hits, updates,
query uptake and cost, then validate on untouched scenarios before claiming
generalization. No task identities or expected answers enter runtime guidance.
