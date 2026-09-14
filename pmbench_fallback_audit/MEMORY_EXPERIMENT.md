# Memory intervention pilot

## Portable prospective-memory version (current implementation)

`--mode selective --memory-version portable` uses the reusable package in
`prospective_memory/`, with a separate public-message-only PM-Bench adapter.
Registration, trigger assessment (ACT/CHECK/WAIT), and lifecycle management are
separated. Menus never enter the memory compiler/assessor; the actor still resolves
current task handles. Sources are discovered from the public interface.

See `../prospective_memory/README.md` for the contract, command, and limitations.
The completed validation is 49 tests (26 independent core, 11 adapter/provider,
4 runner, 8 old v1/v2) plus a 10-scenario scripted demo. No portable live-model
experiment has run; there is no new performance result.

`--memory-check-budget` limits CHECK proposals per assessment, not actual actor
queries over a step or run. The adapter cannot infer completion from public
task-handle selections, so it logs attempts without acknowledging success.
The runner saves source/scenario hashes, helper raw outputs/usage/errors, and
`memory_snapshot.json`, as well as the existing logs and metrics. Its snapshot is
the last pre-action adapter state; no simulator-resume CLI is implemented.

The following sections describe the earlier v1/v2 implementations; their test
counts and smoke checks are historical, not portable-method evidence.

## Structured intention variant

Pass `--memory-version v2` to use structured action/trigger/day/channel/status/
evidence records. The default v1 preserves the prior implementation. V2 rejects
task_N record IDs, requires evidence quotes to occur in visible messages, requires
different evidence for revisions, and retains records instead of deleting them.
Record validation is per edit (accepted edits survive rejection of other edits).
The helper also receives explicit check-versus-act and stale-day instructions.
Eight tests cover both variants. These checks enforce structure and quote
presence, not semantic entailment, canonical ID uniqueness, or correct timing;
those still require examining the model's logs. This is a combined intervention
change, not an isolated ablation of any single component.

Helper-output repair: requests now use phase-specific JSON schemas and
chat_template_kwargs.enable_thinking=false, with --memory-max-tokens defaulting
to 2048. Actor output allowance remains 768. A live library-cue smoke check
successfully produced a bank entry and reminder. Five automated tests pass.

Start a local compatible Qwen3-8B server, then run from the repository root:

```bash
.venv/bin/python pmbench_fallback_audit/run_memory.py --mode selective --model Qwen/Qwen3-8B --base-url http://127.0.0.1:30002/v1 --output pmbench_fallback_audit/memory_results/qwen3-8b-selective-01
```

Modes: baseline, heartbeat (auto30), full_bank, always, selective. Use a distinct
output directory for each run; existing directories are rejected. All runs use
empty fallback. --memory-model selects a different helper served at the same URL.

Outputs include manifest, trajectory, metrics, original actor prompts, memory
cycle logs (bank, reminder, errors, latency), and assistant token usage. Injected
reminders are in memory.jsonl, not prompts.log. Actor token accounting remains
unfinished, so total cost comparisons are not yet supported.

The helper receives all new public messages plus eight recent messages. This
extends the paper's window to preserve initial instructions. Cycles run before
action calls, including after channel observations. Bank edits are bounded and
atomic. Invalid assistant content leaves edits unapplied or produces silence;
transport errors abort. Reminders are transient. Private status is not exposed.

The upstream heartbeat derives channel suggestions from simulator task state:
it is an existing scaffold reference, not an information-matched control.

Run tests with:

```bash
.venv/bin/python -m unittest discover -s pmbench_fallback_audit -p 'test_memory_intervention.py'
```

Four tests cover edits, deletion/revision, privacy, silence, input isolation, and
an 80-step scripted integration run verifying empty fallback and transient
reminders. Real-model audits for unobserved time/channels and instruction following
are still required. No performance improvement is established by these tests.
