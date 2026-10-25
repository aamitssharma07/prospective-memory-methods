# Frozen live smoke-test protocol: grounded PIS

Date: 2026-09-22. User approved a small live-model check before a full PM-Bench run.
This is a development diagnostic of the helper module, not agent execution or a
held-out benchmark. No baseline superiority or generalization claim is intended.

## Configuration

- Candidate: `GroundedPISEngine`, policy variant `pis_grounded_v1`.
- Model: Qwen/Qwen3-8B, snapshot `b968826d9c46dd6066d109eabc6255188de91218`.
- BF16, no quantization, nonthinking, temperature 0, 4096 output tokens per call.
- Local vLLM 0.8.5.post1, seed 0, context 32768, compact xgrammar JSON decoding.
- One helper server on GPU 0. No main-agent server is needed; GPU 1 is left free.
- Only instructions, observed fixture text, source capabilities and legitimate
  memory history enter model calls. Expected labels/assertions are scorer-only.
- Freeze cases and policy sources before the first live case; retain their hashes,
  executable source copies, complete helper requests/responses and every error.

## Coverage and pass gate

Use the fixed generic suite `examples/pis_grounded_smoke_v1.json`: positive and
negative events, explicit time, hidden-source checking, multi-source conditions,
unrelated additions, revisions, cancellation and unsupported tools.

The smoke gate passes only if **all case contracts pass**. In particular:

1. Required tasks must actually register; empty memory cannot pass a quiet case.
2. Positive evidence must yield valid ACT proposals, not merely a plausible reason.
3. Negative/future/unsupported evidence must not yield ACT.
4. A needed supported source must produce CHECK before its fixture response is
   supplied; then the response must be used appropriately.
5. Revisions/cancellations must affect the intended record without losing unrelated
   commitments or unchanged prerequisites.

This is a conservative development gate. Report each failed assertion and inspect
its raw trace; passing does not prove full semantic correctness of every record.
Source labels and bounded text assertions are diagnostics, not a gold semantic
equivalence oracle. Do not convert these scores into PM-Bench F1.

## Boundaries

Requests have a timeout and a total call budget. Transport/budget failures are
explicit aborts, not fabricated model decisions or completed score reports.
Fixture tool replies are supplied by the diagnostic host, not a main-agent LLM;
this cannot establish that an autonomous actor will follow checking guidance.
The test does not execute ACT actions or invent completion acknowledgements.

No policy/case tuning during the run. Any subsequent change requires a separately
named run and preserving this attempt. Do not proceed automatically to the full
PM-Bench week if the smoke gate fails. Save the outcome and update project context
after audit. Stop only the server created for this test and verify GPU release.
