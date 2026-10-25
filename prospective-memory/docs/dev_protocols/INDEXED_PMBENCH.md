# Exploratory end-to-end indexed-memory candidate

This connects the sentence-indexed registration candidate to the existing public
PM-Bench adapter. The user explicitly requested PM-Bench evaluation despite the
failed generic registration gates. It is an exploratory combined pipeline, not
a promotion or a claim that the 88.2% registration score predicts action F1.

## Composition

1. The public adapter removes action menus/handles and supplies host messages,
   available state channels, source-labelled observations and the visible day.
2. The unchanged `IndexedExtractor` classifies each sentence/line unit. The
   `PreservationBank` retains all original messages and exact source spans.
3. A new same-model resolver matches explicit revision/cancellation proposals to
   stored pending requests. Only an accepted, known target is applied; updates
   append exact text, never regenerated action/condition summaries. Ambiguous or
   invalid resolutions remain deferred and visible to the monitor.
4. A new monitor reads selected requests, full original context, accepted update
   history and current observations. Full source messages are deduplicated in
   the prompt. It proposes ACT/CHECK/WAIT through the existing evidence gates.
5. The actor receives ordinary reminder/check guidance and retains the final task
   choice. No hidden due-task list, target label or correct handle enters the helper.

`IndexedMemoryEngine` keeps all advertised sources eligible; the extractor cannot
silently omit a channel. PM-Bench enables its host-controlled `cross_scope=True`
option so day changes do not delete/filter intentions intended for a later day.
Source messages retain their original day labels, and the monitor receives the
current label; temporal validity remains a model interpretation, not a software
guarantee. Other hosts default to isolated scopes.

The core checks current referenced evidence, known intention identity, source
permissions, query budgets and stable-ID duplicate delivery. These checks do not
prove that the cited text semantically establishes every condition. The resolver
can choose a wrong but structurally valid target, and the monitor can make
semantic mistakes. Deferred updates are shown, not treated as accepted changes.

PM-Bench supplies attempts, not authoritative execution acknowledgements. This
candidate therefore does not mark a proposed task complete and does not support
the general `acknowledge` API yet. This can allow repeated proposals under new
evidence IDs. An indexed snapshot includes both source bank and core projection;
restoration validates consistency without invoking a model.

## Run

Use two servers with the same pinned Qwen3-8B BF16 weights/configuration:
actor on port 30003 with default `auto` grammar, helper on port 30002 through
`prospective_memory.serve` with whitespace-free grammar. The actor schema cannot
use the helper's xgrammar configuration because it includes unsupported maxItems.

```bash
.venv/bin/python pmbench_fallback_audit/run_memory.py \
  --mode baseline --model Qwen/Qwen3-8B \
  --base-url http://127.0.0.1:30003/v1 \
  --output pmbench_fallback_audit/memory_results/<new-baseline-directory>

.venv/bin/python pmbench_fallback_audit/run_memory.py \
  --mode selective --memory-version portable --memory-policy indexed \
  --model Qwen/Qwen3-8B --base-url http://127.0.0.1:30003/v1 \
  --memory-base-url http://127.0.0.1:30002/v1 --memory-max-tokens 1536 \
  --output pmbench_fallback_audit/memory_results/<new-memory-directory>
```

Both use temperature 0, thinking disabled and corrected empty actor fallback;
actor output cap 768. The runner snapshots policy code and scenario, saves full
helper outputs and source banks, logs actor dialogue and produces benchmark
metrics. `summarize_memory_pair.py <baseline> <candidate>` audits completed pairs
without inference; it fails on incomplete runs rather than reporting them as done.

Primary comparison: matched Set-F1 plus TP/FP/FN, precision, recall, queries,
fallback frequency and helper cost. Counts of reviewed units or reminders are
diagnostics, not success measures. Single traces do not establish significance
or cross-model generality. Historical 42.0% baseline is not the matched control.
