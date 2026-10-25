# Selective Consistency Reruns

The user selected only mismatched-setting pairs, keeping the updated v15
methodology. Submitted record: `v15_consistency_reruns_20261023.json`.

## Scope

| Main | Helpers | Jobs | Reason |
|---|---|---|---|
| Qwen3-32B | Qwen3-1.7B, 4B, 8B | 1553054-1553056 | Effective actor KV capacity was below earlier NVL serving |
| Ministral-3-3B BF16 | Qwen3-1.7B, 4B, 8B, 32B | 1553057-1553060 | Restore earlier unquantized BF16 checkpoint |
| Ministral-3-8B BF16 | Qwen3-1.7B, 4B, 8B, 32B | 1553061-1553064 | Restore earlier unquantized BF16 checkpoint |

The other 21 unique pairs are not rerun. All original 32 full-dataset results
remain intact. The 0.6B native-window overflows are not a changed serving
setting and are not repaired through hidden history truncation or a context
extension in this task.

## Method and Settings

- Inference source hashes for run.py, adapter.py, improved_engine.py,
  registration_guard.py, source_routing.py, benchmark scorer/runtime, and
  registration.py still match the successful GPT-v15 run 1537307.
- Keep query-first, legacy query handoff, source routing, scope/registration
  grounding, bounded priority, output caps of 768, and temperature zero.
- No over-selection fix, new history-compaction policy, or efficiency change.
- Use the recorded earlier 96GB-class H100 NVL allocation on crest-g002,
  co-locating actor/helper on one GPU, with reference memory fractions and
  graph settings. Do not use the mismatched 80GB allocation for these reruns.
- Pin expected model revisions in the spec and validate the actual prepared
  checkpoints before inference; abort on an unexpected revision/quantization.
- Three 1.7B-helper pairs lack a historical same-pair full run. Their specs
  explicitly identify the same-actor 4B-helper serving template; the actual
  1.7B checkpoint revision remains pinned. Do not describe these as exact
  historical same-pair reproductions.

## Validation and Execution

89 offline tests pass, including selection scope, quantization and capacity
checks, transport-versus-context failures, and preservation of public probe
inputs. Bash launcher syntax also passes. These are not live GPU test results.

Each job checks the assigned GPU, actual checkpoint revisions and quantization,
native context, graph/memory settings, and effective KV-cache capacity against
the reference. A separate admission diagnostic replays the largest serialized
saved public actor/helper requests. Raw responses, parsed output, usage, errors,
and durations remain in the job's `consistency_admission` directory. Probe
outputs do not enter the scored benchmark or repair model answers.

Unexpected serving/configuration or transport failures stop that job before
benchmarking. If historical capacity matches but a public request exceeds that
budget, the rejection is saved as a limitation and does not silently change
the input; the normal report-only smoke/full benchmark still evaluate the
method under those resource constraints. Invalid predictions remain empty/
incorrect. This is not a claim that matching old capacity eliminates every
context overflow from the longer updated-method prompts.

Jobs are sequential and begin only after existing GPT follow-up job 1553053
terminates. All 11 actual scheduler requests were checked: correct gpu
partition/QoS, one H100, requested node crest-g002, zero dependency mismatches.
GPT jobs 1553051-1553053 were left untouched. No additional GPT inference
was submitted by this task.

## Results

Fresh output root:
`experiments/rgpm/runs/registration_v15_consistency_20261023`.
Job IDs make each pair's directory unique. Preserve original and rerun
results, and report all 11 outcomes, not only improved F1. Do not replace
earlier primary results until the corresponding rerun completes and is
validated. If a serving guard fails, report that failure rather than a
fabricated full-dataset score or an undocumented fallback configuration.
