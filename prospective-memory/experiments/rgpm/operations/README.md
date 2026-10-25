# GPT Midnight Recovery

The user authorized one credit-gated retry after midnight Chicago time, following
the October 24 credit check. Target: October 25, 2026, 00:05 America/Chicago
(05:05 UTC). Slurm may start later if the requested GPU is busy.

The submission record is `../launches/gpt_midnight_retry_20261025.json`. It records
the actual job ID, scheduler eligibility, operational hashes, parent runs, output
paths, and conservative reservations for earlier credit-rejected calls.

Only these two pairs are retried, sequentially on one H100 NVL:

1. GPT-5.4 + Qwen3-4B: resume the existing benchmark at its 73-step checkpoint.
   Reuse its completed six-step smoke test.
2. GPT-5.4 + Qwen3-8B: resume the interrupted smoke test (zero committed steps),
   apply the previously authorized report-only smoke admission, then run PMBench.

The completed 1.7B/32B helper results and all local-model jobs are untouched.

## Admission and Preservation

- A single minimal GPT-5.4 request runs before either helper server is started.
  It uses the repository `.env` key without recording the key, and retains the
  request, response/error, usage, request ID, and duration under the job attempt.
- If that request fails or returns missing usage, the job stops. It does not
  submit additional jobs or poll the paid endpoint repeatedly.
- No inference, prompt, parser, scoring, token-limit, or methodology file changes
  are required. Each phase loads and verifies its original frozen source tree,
  and the original resume fingerprint must still match.
- Old frozen trees omitted two unused baseline imports needed to import the
  shared harness. Their current files are separately hash-pinned in the plan.
- All original calls, failed attempts, raw responses, snapshots and checkpoints
  remain in place. Resume appends new sessions and refreshes normal status and
  analysis outputs. New serving details are retained separately and in events.

## Spending Guards

Existing smoke/full limits remain 24/300 actor calls and 500,000/4,000,000 actor
tokens, including prior attempts in the same run. Both roles retain 768 output
tokens. The separate credit diagnostic is limited to one request.

The original budget guard correctly blocked after a credit rejection because
the provider supplied no usage. Recovery only recognizes an explicit saved
HTTP 429 `credit_balance_exhausted` error with no response or usage. Instead of
inventing zero measured usage, it charges the original guard's conservative
request reservation against the existing ceiling. The original usage stays
null, so cost analyses continue to identify it as unknown. These reservations
are recorded by call ID in the plan and session events. They are budget
reservations, not measured billing or a universal tokenizer guarantee.

Unmatched call starts, connection failures, other errors with unknown usage,
new missing usage, exhausted call limits, and exhausted token limits still
block execution. The wrapper does not disable those guards globally.

## Offline Verification

```bash
PMBench/.venv-sglang/bin/python -m unittest discover \
  -s experiments/rgpm/operations -p 'test_*.py' -v
bash -n experiments/rgpm/operations/retry_gpt_after_midnight.sbatch
```

Tests verify real frozen resume fingerprints before any model call, the
midnight gate, no server launch after failed credit admission, preserved null
usage, conservative reservations, and continued call/token/missing-usage stops.
