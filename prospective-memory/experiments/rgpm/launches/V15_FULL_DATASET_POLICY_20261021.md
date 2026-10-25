# Full-Dataset Evaluation Policy

The user requested full-dataset F1 evaluation even when model-quality smoke
checks fail. This changes benchmark admission, not the inference methodology.
Apply it to every remaining pair, not only pairs with promising smoke scores.

## Admission

- New local jobs use `SMOKE_ADMISSION_POLICY=report_only`.
- Smoke still runs, and `smoke_gate.json` keeps the original `passed`, all
  check outcomes, metrics, and semantic errors. A separate
  `admitted_to_benchmark` records permission to proceed.
- Complete analyzed smoke runs proceed despite semantic, coverage, accuracy,
  or invalid-response checks failing. Invalid actor predictions remain
  empty/incorrect, never replaced with evaluator answers.
- Crashes, incomplete smoke execution, and artifact-contract failures still
  block admission. Such pairs are reported as incomplete, not assigned a
  fabricated full-dataset score.
- Source-bound evidence guards and all registration/assessment logic remain
  unchanged. Unsupported updates are still rejected inside the benchmark.
- Strict mode remains the default for other launchers, including GPT.

## Sweep Membership

Original roster: eight non-GPT, non-70B-class actors, each paired with Qwen3
1.7B, 4B, 8B, and 32B helpers (32 total combinations).

Retained full runs from the original launch:

- `1537334`: Qwen3-0.6B / Qwen3-32B, completed 80 steps.
- `1537338`: Qwen3-1.7B / Qwen3-32B, running when replacements were submitted.

New jobs `1538265` through `1538294` cover the other 30 combinations. Exact
model assignments, original indices, exported flags, and submission commands
are in `v15_report_only_replacement_20261021.json`. Each job has a fresh output
directory under `experiments/rgpm/runs/registration_v15_qwen_four_helpers_report_only_20261021`.

Original smoke-rejected jobs `1537331`, `1537332`, `1537333`, `1537335`,
`1537336`, and `1537337` retain all artifacts. Their full-dataset attempts are
the first six replacement jobs. Original pending jobs `1537339` through
`1537362` were held, then canceled only after replacements were accepted.
No running job was canceled; no output was deleted or overwritten.

## Verification

- 83 offline tests pass, including preserving failed smoke outcomes while
  permitting admission, and refusing admission for incomplete execution.
- Replacement partition, QoS, GPU-count, and dependency audit: 30 jobs
  checked, zero mismatches.
- Two-GPU pairs use `gpu-res-01` partition/QoS; same-model pairs share one
  server on `gpu`. Jobs run sequentially after original running job `1537338`.
- Main and helper output caps remain 768 tokens.

## Reporting

Compare full 80-step metrics, not smoke scores. Report smoke errors, invalid
responses, incomplete runs, and protocol differences transparently. Retained
completed/running pairs used strict smoke admission; replacement pairs use
report-only admission. Both execute the same inference methodology. Analyze
the union of the two retained full runs and the 30 replacements, not old
canceled or smoke-only attempts as additional independent benchmark runs.
Experiments 1 and 2, prior methodology outputs, and the completed GPT run are
unchanged. This sweep does not request additional GPT inference.
