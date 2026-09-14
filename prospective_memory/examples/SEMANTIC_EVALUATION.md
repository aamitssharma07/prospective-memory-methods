# Independent live-model diagnostic, version 1

`semantic_cases_v1.json` was authored before inspecting any live portable-policy
outputs. It contains 10 independent, small natural-language streams: 30 ticks,
11 initial instructions and 9 expected ACT occurrences. It uses no PM-Bench
data or action menus. This is a diagnostic suite, not a representative new
benchmark or a statistically independent generalization claim.

Run with:

```bash
.venv/bin/python -u -m prospective_memory.evaluate \
  --cases prospective_memory/examples/semantic_cases_v1.json \
  --model Qwen/Qwen3-8B --base-url http://127.0.0.1:30002/v1 \
  --max-tokens 4096 --max-query-rounds 1 \
  --output prospective_memory/results/qwen3-8b-semantic-v1-20260911-01
```

The destination must not already exist. The runner saves the frozen case file,
case/policy/runner hashes, inference payloads and raw outputs, token usage,
per-tick state/decisions and final metrics. The compiler/assessor prompts are the
same `prospective_memory/llm.py` used by the PM-Bench adapter. Prompts and cases
must remain fixed while collecting results; revisions require a new run/version.

The model receives only typed instructions, pending intentions, actual observed
text and available source names. Case notes, expected labels, future observations
and unrequested pull responses do not enter its input. Up to one CHECK source
per assessment and one extra query/assessment round per tick are permitted.
For the pull-only case, failing to request available evidence counts as a missed
trigger; successful matching after an unsolicited oracle observation is not
substituted for monitoring.

Each ACT is aligned to its intention's original instruction provenance for
scoring. Additional intentions/duplicate ACTs are counted as false positives,
while the same intention across a tick's query rounds counts once. A wrong-time
ACT is a false positive; a missing right-time ACT is a false negative. Exact-tick
accuracy includes quiet ticks and must not replace TP/FP/FN or trigger recall.

This scorer does not semantically grade the generated action description. An ACT
for a malformed or misinterpreted action can share the correct provenance, so
report raw trigger-proposal scores separately from manual action-fidelity review.
ACTs are not executed, and the harness does not send completion acknowledgements
or use gold labels to update the live memory bank. Execution success, reminder
delivery latency in a real application and total agent utility are unmeasured.

Initial instructions are explicitly identified by this host; this does not test
registration from arbitrary unstructured narration as comprehensively as the
PM-Bench adapter does. Cases are short, generally explicit, and each starts with
a fresh bank. Do not compare their F1 numerically with PM-Bench Set-F1 as though
they were scores on the same task distribution.

`tests/test_semantic_evaluation.py` has 16 passing fixture tests for the evaluation
machinery, including label isolation, query visibility, false alarms/misses,
provenance, duplicates and query-budget boundaries. They are distinct from
subsequent live-model measurements.
