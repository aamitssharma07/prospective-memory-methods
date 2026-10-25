# Actor readiness correction

Evidence: completed Qwen3-8B run `qwen3-8b-1503073` achieved recall
0.9012 but precision 0.1718 and F1 0.2885. It selected 425 actions,
with 352 false positives. The preceding run achieved F1 0.5269.

Saved memory traces contain 128 ACT, 146 CHECK and 6575 WAIT decisions
across repeated observation cycles; these counts are not unique task outcomes.
On Monday d1_s1 the helper proposed breakfast medication, requested clock
information and left other triggers unresolved. The actor nevertheless selected
eight actions, including pending portal and grocery obligations and distractors.
The shared adapter rendered ACT/CHECK guidance but omitted WAIT assessments.

The Experiment 3 adapter now includes WAIT action/condition/reason fields and
explicit readiness guidance. The actor still controls execution and may correct
helper mistakes using current evidence. No action is filtered using task truth,
and no menu entries are removed. The runner enables the existing explicit source
query handoff. Actor/helper remain Qwen3-8B with max_tokens=768.

The manifest records actor_guidance=readiness_v1 and query_handoff=explicit;
source hashes prevent resuming an old run with this changed configuration.
Raw calls, parsed outputs and returned actor guidance retain the existing trace
and checkpoint contract. Existing results remain available for comparison.

Validation: nine Experiment 3 regression tests passed; offline preflight passed
method tests, portable adapter/runner tests, launcher syntax, invalid-response
scoring and a scripted artifact bundle. No live inference was performed.

Next evaluation: live Qwen3-8B smoke followed by a new one-model benchmark
bundle. Compare FP, TP, FN, exact sets and F1 against both earlier Experiment 3
runs and base/base+PIS. This change has no measured F1 improvement yet. Full WAIT
guidance adds input tokens; inspect cost and actor uptake during the smoke.
