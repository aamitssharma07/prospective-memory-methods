# GPT handoff comparison: 2026-10-15

Completed exactly two independent GPT-5.4 calls on the saved Monday m3 context
from smoke job 1534994. The context ends after GPT checked clock and the helper
offered CHECK email, with one query remaining. No later email reply, expected
task answer or scoring label was supplied to either request.

| Handoff | GPT response | Took offered email check |
| --- | --- | --- |
| Original | choose B, task_ids=[] | No |
| Query-first | query_state, channel=email, task_ids=[] | Yes |

The original request exactly matches its saved request. The revised request
retains the same history, message count, schema, model, temperature and extra
parameters, appending only the query plan to the final handoff. Both calls use
max_tokens=768 and temperature=0. SDK retries are disabled.

Both responses passed JSON/schema/finish-reason validation. Actor usage totaled
3,079 tokens (3,028 prompt; 51 completion). The two provider-reported usage.cost
fields sum to USD 0.00825165, with cost present for both calls. Calls took
3.5589 and 1.6100 seconds respectively. calls.jsonl retains raw and parsed
responses, complete requests, provider request IDs, usage, timestamps and DUR.
manifest.json hashes the original inputs and archives the implementation.

This pair reproduces the original skipped query and observes the desired query
under the revised handoff. It is one development context, one call per variant,
with no simulation continuation or repetitions. It does not establish that the
report would be selected correctly after the query, an F1 increase, or a
reproducible/general improvement. Temperature zero does not eliminate variance.

No helper inference, GPU job, full smoke or full benchmark was launched by this
diagnostic. The next evaluation is a bounded GPT smoke with query_first enabled,
retaining the zero-FP/zero-FN gate before any full benchmark.
