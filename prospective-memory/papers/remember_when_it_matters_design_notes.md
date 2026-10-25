# "Remember When It Matters" — models and comparison design

Wu et al., Meta AI, arXiv:2607.08716v1, 10 July 2026.
Extracted from `papers/remember_when_it_matters.pdf` on 2026-09-23.
Reference for designing our own multi-model comparison.

## Models

| Role | Models |
|---|---|
| **Action agent** (varied) | Claude Sonnet 4.5 (weaker), Claude Opus 4.6 (stronger) |
| **Memory agent** (fixed) | Claude Opus 4.6 for every prompted experiment |
| **Open-weight study** | action Qwen3.5-122B-A10B (frozen); memory Qwen3.5-27B (trained) |

They vary the **action** agent and hold the **memory** agent fixed at a frontier
model. The only place a different memory model appears is the training section.

## Benchmarks and metric

- Terminal-Bench 2.0: 85 of 89 tasks (4 docker failures excluded), binary
  verifier, pass@1.
- τ²-Bench: airline 50, retail 114, telecom 114 = 278 tasks per configuration,
  single sampled conversation per episode, pass@1.
- Reported as per-domain pass@1 plus **macro** (domains equal) and **micro**
  (task-weighted) averages. Both are reported because they disagree.

## Comparison design

1. **Paired, action-agent-invariant.** The action agent is unchanged between
   baseline and memory runs; only the memory module is added. Same structure as
   our baseline/candidate pairs.
2. **Two action-agent strengths**, to test whether memory merely compensates for
   weak capacity. Gains are larger for the weaker agent (+8.3 pp Sonnet vs
   +2.4 pp Opus on Terminal-Bench) but do not vanish for the stronger one; that
   is their central argument that the effect is not a capacity crutch.
3. **Ablations** (τ²-Bench, Sonnet action + Opus memory) removing one capability
   at a time: full agent (bank + selective reminder/silence); full-bank context
   (bank, no selection); always inject (no silence); injection-only (no bank,
   advisor-style); Mem0 (external vector+BM25 retrieval).
4. **Schedule.** The memory agent runs at the first step and **every subsequent
   step** — exactly one memory call per step. It sees the task description, a
   k=8 recent-message window and the bank; it updates the bank and then emits
   either an injection or silence.

## Main results

| Benchmark | Action agent | Baseline | + Memory | Δ |
|---|---|---:|---:|---:|
| Terminal-Bench 2.0 | Sonnet 4.5 | 37.6% | 45.9% | +8.3 pp |
| Terminal-Bench 2.0 | Opus 4.6 | 43.5% | 45.9% | +2.4 pp |
| τ²-Bench (micro) | Sonnet 4.5 | 55.0% | 61.8% | +6.8 pp |
| τ²-Bench (micro) | Opus 4.6 | 66.2% | 68.7% | +2.5 pp |

Ablations (τ²-Bench, macro / micro): full agent 64.3 / 61.2; always inject
63.5 / **61.5**; full-bank 61.5 / 58.6; injection-only 61.0 / 60.8; Mem0
62.1 / 60.8. **Always-inject beats the full agent on micro**; the paper
attributes the 0.3-point gap to run variance and leans on the macro average.

Training (Table 4): base Qwen3.5-27B memory **hurt** (reward 0.709 → 0.693,
−0.016); SFT +0.011, GRPO +0.025. Transfer to Terminal-Bench: +3.5 pp.

## What this means for our multi-model plan

1. **They never vary the memory model in the main results.** Our hypothesis is
   about a *cheap monitor*, so the interesting grid — memory-model strength
   crossed with action-model strength — is the one they left open. That is a
   genuine gap to occupy, not a replication.
2. **Their own evidence says an untrained small memory model makes things
   worse.** Base Qwen3.5-27B degraded reward; only SFT/GRPO made it positive.
   We run Qwen3-8B, untrained, as *both* action and memory. Expect the
   small-memory-model condition to be weak, and treat that as the finding
   rather than a failure.
3. **One memory call per step, not one per intention.** Their memory agent makes
   exactly one call per step. `pis_source_bound_v3` makes ~26 (one per pending
   intention), which is 97% of our wall clock. Any cross-model comparison we run
   will be dominated by that architectural choice unless we fix it first.
4. **No error bars anywhere.** They report single runs and invoke "expected run
   variance" without quantifying it. We already know our own Set-F1 can be
   identical across runs that differ on 21% of steps, so we should report
   repeats — this is somewhere we can be stricter than the paper.
5. **Report two averages.** Their macro/micro disagreement is instructive: the
   ranking flips. Our analogue is Set-F1 versus cross-day/update retention,
   which already disagree. Report both, and say which one the claim rests on.
