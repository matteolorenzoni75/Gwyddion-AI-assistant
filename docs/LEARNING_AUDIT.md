# After labeling: audit before the first supervised model

The expert labeler keeps a private database at
`%USERPROFILE%\AFM_Copilot_Private_Audits\labeling\labels.sqlite3`.
Do not upload the SQLite database: it contains paths, specimen/group IDs and operator notes.

## Run the safe audit

```powershell
cd C:\AFM_image_wizard
git switch dev/image-wizard
git pull --ff-only origin dev/image-wizard
.\.venv\Scripts\python.exe -B -m pytest tests\test_learning_audit.py -q
.\.venv\Scripts\python.exe -B -m afm_copilot.learning_audit
```

The final command prints **aggregate JSON only**, never filenames, paths, notes,
hashes, specimen identifiers or pixels. Share its terminal output, not SQLite.

Interpret `labeled` as the number with human classifications, including uncertain.
`morphology_counts` displays classes; `specimen_groups_per_partition` counts
independent group IDs in train, validation and holdout; `blockers` lists
scientific or split-integrity gaps. `training_ready` checks minimum data
readiness only, not the quality of human labels or external validity.

The initially selected 244 images can be an extensible labeled corpus.
The 268 raw files counted by the separate importer audit are not automatically
244 unique or independent images. Byte-identical scans and related images
of the same specimen/session must never cross train/validation/holdout.

After the audit, build a conservative offline classifier baseline and
validate by specimen, including per-class confusion, macro-F1, abstention
and label-randomization controls. Do not automatically deploy model suggestions
or optimize corrections to reduce Sq.
