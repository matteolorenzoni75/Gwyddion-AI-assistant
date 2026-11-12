# AFM Copilot: operator feedback and self-learning status

## What is present now

The deterministic engine, GUI, PyGwy conversion and quality guards are real,
but **there is no automatically trained or updated morphology classifier**.
The GUI `Review & masks` can propose or preview masks, save semantic reviews
and now record explicit operator decisions for future model development.

The repository also contains reproducible synthetic labelled scans
(`tools/make_dataset.py`) and a versioned `knowledge/` corpus. Those are
training *resources* and human-readable findings, not a running self-learning
pipeline. The historical ExtraTrees experiment in `C:\AFM_Automation`
is separate from this application and has not been promoted as its model.

## Phase 1 implemented: safe feedback capture

1. Open a scan in the desktop GUI, choose the morphological family and enter
   visible evidence. Optionally preview the guarded plan.
2. In `Review & masks`, choose **Confirmed**, **Rejected** or **Uncertain**.
   Confirmed means that the selected family is an expert-verified label.
3. Explicitly check **This is a reviewed TRAINING scan (not blind/test)**.
4. Click **Record operator feedback privately**.
5. Every event is appended to
   `%USERPROFILE%\AFM_Copilot_Private_Audits\learning_feedback\operator_feedback.jsonl`.
   A private random key in the same directory allows content-derived IDs
   without recording original filenames or paths **in the shareable ledger**.
   A separate local `private_source_index.jsonl` maps anonymised IDs back
   to approved files for future curation. It includes confidential paths:
   **never upload or commit it**. The entire folder remains private.

   The 244-image **test** set declared by the operator (and the entire raw
   archive `C:\AFM_Automation\OLD input IMAGES` that hosts it) is excluded
   from feedback for training. The earlier inventory of **268 TIFF/IBW files**
   counts instrument files, not necessarily unique evaluation images.
   Approved training scans must be stored separately under
   `%USERPROFILE%\AFM_Copilot_Training_Approved` (or an explicitly
   configured `AFM_TRAINING_ROOT`). This directory is **not created or
   populated automatically**. Do not copy holdout material there.
   Physical-specimen lineage still needs independent review before training.
6. Only confirmed, non-uncertain labels with evidence are marked eligible for
   future training. Rejections and uncertainty are retained as review history,
   not silently converted into positive labels.

The source image is never modified. Recorded feedback never automatically
changes a Gwyddion recipe, mask, detector threshold, or model. Blind files
under `export/`, stems such as `scan-053`, and recognised blind/test/holdout
directories are refused as training sources. **Directory heuristics cannot
replace deliberate operator dataset assignment**.

The ordinary `Save review` button remains an independent, advisory or
restrictive planning annotation. It is not a training approval.

## Phase 2 partially implemented: feedback curation

The read-only `afm_copilot.curation` module now counts **unique, explicitly
confirmed** scan identities, removes duplicate confirmations from counts and
holds any contradictory, rejected or uncertain evidence for operator review.
It prints safe aggregates only, never IDs, paths or free-text evidence.

Run:

```powershell
.\.venv\Scripts\python.exe -B -m afm_copilot.curation
```

A candidate count is **not** a model-training approval or a validated
training set. Outstanding Phase 2 work:

- Resolve conflicting feedback **explicitly**, keeping the append-only audit.
- Group scans by original specimen/session (HMAC byte identity alone does not
  identify related scans of the same physical sample).
- Keep the blinded regression corpus and an independently held-out
  real-instrument evaluation set permanently outside training.
- Extract the existing numerical descriptors from only approved scans,
  version the feature schema and curate the training split.
- Maintain an auditable model registry: dataset snapshot, split, parameters,
  metrics, model checksum and reviewer approval.

## Phase 3 not yet implemented: candidate training and evaluation

Compare a compact classical baseline (e.g. ExtraTrees/logistic regression)
against current deterministic heuristics on genuinely unseen specimens.
Report per-family precision/recall, macro F1, abstention rate, calibration,
rejection errors and actual morphology/height preservation after proposed
processing. Never optimise RMS downward as a quality objective.
Use label-randomisation and leakage tests. Prohibit auto-deployment of a
candidate that does not beat the current rules on external validation.

## Phase 4 not yet implemented: guarded model suggestions

A future model may rank morphology and propose a mask. It must not override
operator refusals, blind-test constraints, explicit manual masks or the
existing conservative plan. Promotion requires a reviewed change and
repeatable regression tests. No unattended online updating.

## Developer verification

From `C:\AFM_image_wizard`:

```powershell
git pull --ff-only origin dev/image-wizard
.\.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B tools\diff_export_baseline.py
.\.venv\Scripts\python.exe -m afm_copilot.gui
```

On 2026-11-09, the original Windows branch had 229 passing tests before
the raw-audit and feedback changes. Nine new feedback tests, plus eight existing
morphology tests, passed in a separate local Python 3.13 run. The **entire
updated suite must be rerun on Windows** before merge. The local container
used for this focused test lacks `gwyfile` and `mcp`; that is an
environmental collection failure, not evidence of a project regression.

## Latest Windows verification

On 2026-11-09 at the confirmed `dev/image-wizard` update before the
curation additions, the user ran the real Windows environment:

- `246 passed, 1 warning` in 51.05 seconds;
- baseline: `44 unchanged, 0 changed, 12 without a clean surface`;
- Gwyddion 2.70/Python 2.7.16: `can_process`, `import_gwy`,
  `modules_registered` all OK.

The warning was a Python raw-audit docstring escape and was fixed after this
run. Full Windows tests must now be rerun with the new curation additions.
