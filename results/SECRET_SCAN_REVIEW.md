# Credential-Pattern Review

The first raw-packaging pass verified 156 of 157 groups but stopped the
Experiment 2 group on two apparent `sk-` matches inside generated task labels.
The detector had matched the suffix of `task-...`/`Task-...` as though it were
an API-key prefix. Neither hit matched any known local credential value.

The affected log is
`prospective-memory-reaearch/data/PMBench/runs/full_matrix/jobs/exp2-ministral-3-3b-1502604.log`.
No matched value is reproduced here. The boundary check was corrected for
generic token formats only; known credential values still match exactly even
when adjacent to other characters. Unit tests cover both cases.

All 753 files in the affected group were rescanned and compressed using the
corrected boundary rule, with full decompressed per-file hash verification.
The other 156 groups had passed the stricter original superset pattern.
The final group manifest records both scanner-source hashes and this review.

No raw file was redacted or modified. All 84,259 published raw files retain
their original byte hashes. The initial failed packaging outputs and job log
remain in the local publication workspace for audit; they are not release assets.
