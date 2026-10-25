# Single-model smoke readiness

Reviewed 2026-10-01. Status: offline tests pass; live smoke is blocked by the
output contract and the correctness/configuration issues below.

## Selected agents

- Main/action agent: `Qwen/Qwen3-8B`.
- Memory/helper agent: `Qwen/Qwen3-8B`.
- Method: `sbpm` with span extraction, the current RGPM candidate.
- Target runtime: SGLang 0.5.20, BF16, temperature 0, output limit 768 for
  both agents. Record and verify actual checkpoint/server identities.
- Prefer one served checkpoint for both roles if the actor and helper schema
  probes pass on that server; separate roles do not inherently require two GPUs.
  Serving compatibility and resource availability have not been verified here.

Using the same model in both roles gives the first smoke a direct relationship
to the Qwen3-8B base and author-PIS comparisons. It does not establish that this
is the best helper. Later helper-size ablations should hold the actor fixed.

## Verified offline

The system Python is 3.9 and cannot import this code's Python 3.10 union types;
it also lacks pytest. The existing Experiment 2 Python environment successfully
ran the unittest suites without installing or changing dependencies:

```bash
../prospective-memory-reaearch/.venv/bin/python -m unittest discover -s tests -q
../prospective-memory-reaearch/.venv/bin/python -m unittest discover -s harness -p 'test_portable*.py' -q
bash -n experiments/exp3_method.sh
```

Results: 441 method tests and 33 portable runner/adapter tests passed. Shell
syntax passed. These checks use scripted responses and do not validate model
quality, SGLang compatibility, or the new output contract.

## Findings before live inference

1. The old runner imports `benchmark/sim/pm_bench.py`, not the corrected
   Experiment 1 `PMBench` runner. Its scorer compares selected and expected sets
   without excluding invalid-response fallbacks. Invalid empty output can earn
   exact-match credit on empty-answer steps. Actor fallback is explicitly empty
   in `harness/run_memory.py`, but scoring parity still needs correction.
2. `harness/run_memory.py` creates a fresh-only output directory and writes a
   final memory snapshot. The underlying benchmark writes its trajectory at
   the end. There is no complete atomic per-step runner checkpoint/resume.
   Unified actor/helper attempt records, stage tracing and offline exports
   required by `OUTPUT_CONTRACT.md` are still incomplete.
3. The historical actor prompt log is written before the adapter adds a
   reminder. It therefore is not, by itself, the exact actor request. Preserve
   post-injection messages and every actual request/response attempt.
4. `SourceBoundFairTriggerEngine._assess` overrides the parent assessment loop
   and directly calls `_decide` per intention. The parent's skip-unevidenced,
   stable-WAIT reuse and assessment batching logic is bypassed, despite those
   flags being passed by the launcher. Do not claim those cost controls are
   active for this policy without implementing and testing that behavior.
5. `experiments/exp3_method.sh` requests 4096 helper output tokens and constructs
   a hardcoded vLLM projector identity. It must reflect the chosen 768 limit
   and actual SGLang/model configuration. A cache-directory filename selected
   by sorting is not proof of the loaded checkpoint revision.

## Next smoke sequence

1. Implement the output contract and correct scoring/configuration issues in
   the Experiment 3 execution path, preserving the earlier experiments.
2. Validate the scripted run, malformed responses, stage-failure tracing and
   interruption/resume with zero inference calls.
3. Probe actor/helper structured responses on the selected server.
4. Run a small deterministic diagnostic scenario covering registration,
   revision, cancellation, a trigger, a query and a cross-day obligation.
   Freeze the slice and expected diagnostic checks before model execution.
5. Validate all stored artifacts and regenerate the failure and cost reports
   offline. Separate plumbing success from semantic mistakes by the helper.

No live smoke, server launch, Slurm operation or full experiment was performed
in this review. Full experiment execution still requires explicit user approval.
