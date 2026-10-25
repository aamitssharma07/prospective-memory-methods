# GitHub Handoff

**Publication completed:** [repository](https://github.com/aamitssharma07/prospective-memory-methods)
and [full raw results](https://github.com/aamitssharma07/prospective-memory-methods/releases/tag/research-snapshot-2026-10-25).
See [Publication Status](PUBLICATION_STATUS.md). The clean export vendors child
source, excludes credentials and old research Git history, and preserves the
destination's existing public history. The checklist below records the original
research checkout's risks and remains relevant to future exports; it does not
mean the published repository contains `.env` or broken submodules.

Updated: **2026-10-25**. [Team Context](../TEAM_CONTEXT.md) is the teammate-facing
entry point. This checklist is preparation guidance, not a claim that the
current working tree is safe to push. No commit, staging or push was performed
while creating these context files.

**Full-project scope:** the user also wants complete raw results on GitHub.
See [Full Project Publication](FULL_PROJECT_PUBLICATION.md) for the clean
two-workspace layout and split Release-archive plan. Raw data stays out of
ordinary Git commits, but is not excluded from the intended GitHub publication.

## Publish the Small Context Package

Include `TEAM_CONTEXT.md`, the three `docs/experiments/*_context.md` pages,
the generated `docs/experiments/results/` snapshot, and the exporter/tests in
`harness/`. The snapshot contains numbers, statuses, run references and hashes,
not keys, prompts or raw responses. Reading it needs no GPU, API key or sibling
repository. Older experiment notes remain development history.

The existing `experiments/rgpm/` source/docs tree is also currently untracked.
Review and include its non-ignored code, analysis tools and referenced documents
when publishing the codebase; publishing only the context pages would leave
their code links unresolved. Keep its ignored raw output directories excluded.

## Blocking Security Check: Tracked Environment File

The root `.env` is **already tracked by Git**. Adding an ignore rule does not
remove a tracked file or erase it from history. Do not use `git add .` and push.

Before publishing, intentionally remove it from the Git index while preserving
the local file:

```bash
git rm --cached -- .env
```

This is a suggested user-reviewed staging operation, not something this handoff
has executed. Review whether credentials were ever committed or shared. If so,
revoke/rotate affected credentials before publication and agree on a history
cleanup strategy with collaborators. A new deletion commit alone does not
remove secrets from earlier commits. Do not paste key values into issues, pull
requests, screenshots, context files or command output.

The `.gitignore` now protects future `.env` files, but the existing tracked
root file remains a blocker until handled. Use placeholders only in any future
`.env.example`. Review the selected changes with an appropriate secret scanner
before pushing; no exhaustive repository/history secret scan is claimed here.

## Blocking Portability Check: Nested Repositories

The current index has gitlinks for `benchmark` and `third_party/author_pis`,
but no `.gitmodules` file. `PMBench/` is an untracked nested repository, and
Experiment 2 is a sibling repository outside this checkout. A normal GitHub
clone does not automatically reproduce those local working trees or changes.

Choose and document one publication strategy before treating code as runnable:

1. Publish the necessary patched child/sibling repositories as accessible forks
   and register proper submodules at exact revisions, including `.gitmodules`.
2. Deliberately vendor the relevant reviewed source and preserve upstream
   attribution, licenses and commit provenance.

Do not silently register upstream revisions that omit local scoring/fallback
patches. Do not delete nested `.git` directories or rewrite someone else's
history as a shortcut. The new context snapshot remains readable even while
these source-packaging decisions are pending.

## Raw Data and Backups

Keep large raw traces, run directories, caches, model weights, environments,
logs and checkpoints out of a normal Git commit. Nothing was deleted from
disk. `docs/experiments/results/` is the small, portable reporting layer;
it is not a replacement for the full artifact archive.

Before calling the handoff complete, publish an access-controlled archive or
research-data release and record its URI, access instructions, archive hash,
and mapping to the relative source paths in `snapshot.json`. No such remote
archive location has yet been verified. A teammate must not need to rerun
completed inference to recover the original evidence.

Raw prompts/responses may require a separate privacy review before release,
even when the benchmark scenario is synthetic. Preserve licenses for scenario
data and third-party code.

## Final Review

- Read `TEAM_CONTEXT.md` and verify all three tables load on GitHub.
- Keep the snapshot date and incomplete/failed cells explicit.
- Confirm no credential file, cache, raw trace or model weight is staged.
- Review the existing unrelated modifications/deletions before choosing files to stage; do not revert them automatically.
- Resolve the tracked `.env` and child-repository packaging blockers above.
- Confirm result rows trace back to saved artifacts and never replace missing values with zero or ground truth.
- Commit/push only the intended reviewed files after those checks.

Refresh the compact tables from existing storage without any API calls:

```bash
python harness/export_team_context.py --as-of YYYY-MM-DD
python -m unittest discover -s harness -p 'test_team_context.py'
```
