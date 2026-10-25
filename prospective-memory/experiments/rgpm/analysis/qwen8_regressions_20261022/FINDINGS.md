# Why Two Qwen3-8B Pairs Regressed

Paired full-dataset comparison against the best retained earlier run of the
same main/helper pair. Source paths, public handoffs, call IDs, and complete
counts are saved in `evidence.json`. No inference or job changes were made.

## Established Outcomes

| Main / helper | Earlier TP / FP / FN | Updated TP / FP / FN | Earlier F1 | Updated F1 |
|---|---|---|---:|---:|
| Qwen3-8B / Qwen3-4B | 46 / 35 / 35 | 58 / 123 / 23 | 56.79% | 44.27% |
| Qwen3-8B / Qwen3-8B | 44 / 42 / 37 | 60 / 210 / 21 | 52.69% | 34.19% |

Recall improved, but increased incorrect selections outweighed that gain.

## Observed Mechanisms

1. **The main agent selects many more actions.** With a 4B helper, total
   selections rose from 81 to 181; with an 8B helper, from 86 to 270. Steps
   choosing eight handles rose from zero to three and eleven respectively.
   The JSON schema permitted at most eight in both earlier and updated runs;
   a changed task-array limit does not explain this difference.

2. **Most false selections are premature.** For the 4B helper, 96 of 123
   false positives selected tasks before a later due occurrence in the same
   day's scored trajectory. For the 8B helper, this accounts for 172 of 210.
   Other false positives include distractor actions and selections after a
   prior due occurrence. These categories are offline descriptions, not a
   causal model of each mistake.

3. **Extra selections often extend beyond helper ACT guidance.** With the 8B
   helper, 139 false positives occur across 33 steps with no ACT proposal in
   the current handoff. The earlier run had 12 such false positives across
   12 steps. Total current ACT proposals fell from 93 to 77 even while false
   positives increased from 42 to 210. The helper therefore did not directly
   propose each extra action in that run. With the 4B helper, 31 false
   positives occur on 11 steps with no current ACT proposal.

4. **Helper errors also contribute plausible bad guidance.** In the updated
   4B-helper run's Monday d1_s2 handoff, the helper proposes moving the
   appointment because the portal 'may open a better slot later'. That
   observation is a possibility, not evidence of an opened slot. In Monday
   d1_s1 it has registered the descriptive breakfast scene itself as an
   action. These are specific observed semantic errors, not proof that every
   false positive originated in the helper.

## Concrete Public-Trace Example

In updated Qwen3-8B / Qwen3-8B, Monday d1_s1:

- Scene: breakfast; queried clock: 07:20.
- Appointment portal reply: `(no updates)`.
- Current helper ACT: take the antibiotic at the breakfast occurrence; its
  explanation explicitly says there is no dinner evidence.
- Actor selects eight actions, including finishing the intake form, taking
  11:00 asthma medication, collecting a grocery bag, and distractor actions.
- Evaluator expectation: only the breakfast antibiotic is due.
- Earlier matched run selects only the breakfast antibiotic.

On Monday d1_s2 and d1_s3, the updated 8B-helper run selects eight handles
despite no current ACT proposal and no action due at those steps. Exact
public inputs and response IDs are in `evidence.json`.

## Limits and Next Diagnostic

The evidence supports over-selection and premature execution as the immediate
reasons F1 fell. It does not isolate which change caused the behavior.
Registration, grounding, source routing, and query-first guidance changed
together. More querying (109 -> 160 and 104 -> 160 calls) is observed, not
proven to cause the false selections. Neither updated run has actor-context
rejections or invalid actor responses in the runtime audit.

Next test should be a separate local ablation using saved public-state
examples: vary the actor handoff while holding its evidence, schema, and
model fixed; also test rejection of descriptive scenes and predictions as
new obligations/readiness evidence. Include zero-due, one-due, genuinely
multi-due, cancellation, and recurrence cases. Do not force one action or
restrict the menu using evaluator labels, and do not turn helper proposals
into an authoritative whitelist. No such ablation was launched in this audit.
