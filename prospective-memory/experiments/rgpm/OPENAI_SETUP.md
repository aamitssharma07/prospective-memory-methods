# Direct OpenAI actor

Set `OPENAI_API_KEY` privately in the repository `.env`. Never include the key
in a launch command, report, or chat. Existing OpenRouter settings can remain.

Use these launcher environment settings for direct OpenAI:

```bash
ACTOR_BACKEND=openai_chat
ACTOR_MODEL=gpt-5.4
HELPER_MODEL=Qwen/Qwen3-32B
RUNS_ROOT=experiments/rgpm/runs/registration_v15_openai_full
```

Export them with the other approved flags when submitting
`experiments/rgpm/run_gpt_actor.sbatch`. Do not reuse the saved OpenRouter
submission unchanged. The launcher retains the local probes and smoke gate
before any authorized full run.

The actor uses https://api.openai.com/v1 and Chat Completions with strict JSON,
temperature 0, reasoning_effort none, and max_completion_tokens 768. The helper
remains local, with max_tokens 768. Raw responses, usage, retries, checkpoints,
and provider provenance use the existing audit path. Unknown usage still blocks
budgeted execution. Provider-reported dollar cost may be absent; do not treat
that as zero cost. Keep direct-OpenAI and OpenRouter runs separate in analysis.

The older shared `openai` Responses backend is unchanged. The new `openai_chat`
branch is opt-in and used by Experiment 3 only.

Setup is offline-tested, not yet authenticated or inference-tested. A model
access check does not establish remaining account credit; the smoke must pass.
