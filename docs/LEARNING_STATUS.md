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
   without recording original filenames or paths. Keep this folder private.
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

## Phase 2 not yet implemented: training set curation

- Deduplicate by private scan ID, reconcile repeated/conflicting labels and
  group scans by specimen/session before splitting.
- Keep the blinded regression corpus and an independently held-out
  real-instrument evaluation set permanently outside training.
- Extract the existing numerical descriptors from only the approved training
  images. Explicitly version the extractor and feature schema.
- Keep an auditable model registry: dataset snapshot, split, parameters, metrics,
  model checksum and reviewer approval.

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
