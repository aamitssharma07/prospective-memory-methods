# Remember When It Matters: PM-Bench adaptation proposal

Status: proposed experiment, not implemented or measured.
Source: Wu et al., https://arxiv.org/abs/2607.08716; local PDF:
`remember_when_it_matters.pdf`. Method: sections 3.1–3.5; experiments: section 4.

## What the paper actually does

A separate memory model maintains a bank through explicit edits, then decides
whether to send a targeted, transient reminder to the action agent. The bank has
private status, stable knowledge, and procedural experience. The main experiments
invoke memory at every step, with the latest eight messages and the bank as input.
The action model remains fixed. Training is optional; SFT and GRPO are a later
exploration, not prerequisites for the prompted method.

Selective intervention is promising, but not uniformly superior: Table 2 reports
64.3 macro / 61.2 micro for selective reminders and 63.5 / 61.5 for always-inject.
Table 1's main full-system micro score is 61.8, distinct from Table 2's 61.2.
Do not mix these results or claim that silence always wins. Calling the memory
model every step still costs inference even when it emits no reminder.

## Proposed adaptation

Research question: does a separate intention-memory assistant help a fixed action
model select due tasks and avoid false positives under the empty fallback?

| Paper component | PM-Bench adaptation |
|---|---|
| Knowledge bank | User-stated intentions, trigger conditions, revisions, cancellations |
| Private status | Pending intentions, uncertainty, evidence still needed |
| Procedural bank | Previously observed channel responses and attempted actions |
| Selective reminder | Suggest a relevant channel check or recall an intention supported by observed evidence |
| Silence | No useful reminder supported by current observations |

At each benchmark step, expose the public task instructions, current vignette,
recent agent-visible messages, and maintained bank to the memory assistant.
First apply validated bank edits; then request one short reminder or silence.
Supply a reminder only to the next action-model call. The action model still
chooses whether to query a channel and which current menu handles to select.

After a channel response, permit another memory cycle before the next action
decision; cap cycles using the existing action/query limits and log their cost.
Keep stable intention descriptions in memory; resolve anonymous task_N handles
against the currently visible menu instead of assuming handles persist.

Example: retain “collect the library book when the hold is ready.” With no recent
evidence, suggest “check the library-hold channel,” not “the book is ready.” After
the action agent obtains a ready response, remind it of the collection intention.
Record an attempted action as an attempt, not evaluator-confirmed success.

## Information boundary

Build assistant input from the same messages available to the action agent. Never
pass due_now, scorer labels, hidden channel state, full scenario task-state
objects, unobserved time, or future events. The assistant recommends checks; it
does not receive free channel observations. Every actual query uses the normal
environment interface and counts against the same budget.

Invalid assistant edits leave the bank unchanged; invalid intervention output
produces silence and is logged separately. Action-agent failures use empty
fallback. Neither path uses the answer key. Semantically sensible unparsed
responses should not be interpreted as evidence of forgetting without inspection.

## First experiment

Use Qwen3-8B as the fixed action model and Qwen3-8B as the memory model initially.
It is an existing anchor without the 70B quantization confound. This tests role
separation before introducing a stronger helper or training.

Compare these conditions on the same scenario and generation settings:

1. Action model alone, empty fallback, freshly run end to end.
2. Existing automatic heartbeat, empty fallback.
3. Maintained bank exposed in full each step, without reminder selection.
4. Maintained bank plus a reminder every step.
5. Maintained bank plus selective reminder or silence.

Use identical bank-update interfaces, budgets, and model settings across the
memory conditions. An advisor without a bank is a useful follow-up ablation.
Extra helper calls are a compute confound: record tokens and calls, and add an
extra-call self-review control before claiming a benefit specific to memory.
Repetitions at temperature zero test runtime stability; additional independently
generated scenario weeks are needed to assess generalization. Do not train on
the evaluation week or interpret its 80 dependent steps as independent samples.

Report TP, FP, FN, Set-F1, action and assistant failure rates, channel-query count,
memory calls, token cost, reminder frequency, and latency. Break performance down
by narrative, clock, and hidden-channel cues and by updates/cancellations. Use
independent corrected-policy trajectories for the method comparison; existing
counterfactual audit scores are diagnostic references.

Success means better correct-task recall without excessive false positives or
query cost, particularly for hidden-channel intentions. Whether the gains justify
the extra inference must be measured. A stronger memory model and training can
be tested after this initial mechanism is established.

## Code seams and next implementation work

`PMBench/sim/pm_bench.py` constructs action-model messages, processes query_state,
and appends observed channel responses. These are candidate interception points.
Introduce a separate adapter in the experiment layer that accepts only visible
messages and returns bank edits plus transient context. Add boundary tests for
unqueried channels, unavailable time, stale handles, cancellations, invalid
assistant output, and reminders being removed after one action call.

This document specifies a reviewable pilot. No new model runs, training, or
benchmark modifications were performed while preparing it.
