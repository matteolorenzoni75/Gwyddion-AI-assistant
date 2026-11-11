# AFM archive organizer — local-only workflow

Target Windows: C:\AFM_Automation\All AFM Data (recursive, large, multichannel).
All raw files and all private logs stay on the operator's PC.

## Implemented now

- Read-only full inventory of ordinary files, retaining all sidecars and multichannel AFM containers.
- SHA-256 identifies exact duplicates; filenames suggest repeat series, but do NOT prove repeated acquisitions.
- Preview writes PRIVATE_flatten_plan.json outside source and Git. Its console output is aggregate only.
- Explicit apply can MOVE all files into one flat directory, using collision-safe names that encode old relative paths.
- Re-verify sizes, timestamps and hashes; never overwrite; append private move journal; support partial resume.
- Remove ONLY empty subdirectories after move. No recursive deletion, no duplicate deletion.
- Refuse execution if the source contains labeled images whose stored database paths would break.
- All genuine trace/retrace channels and different AFM signals stay in their original files.

## Safe preflight on Windows

```powershell
cd C:\AFM_image_wizard
git pull --ff-only origin dev/image-wizard
.\.venv\Scripts\python.exe -B -m pytest tests\test_archive_organizer.py tests\test_channel_safety.py -q
.\.venv\Scripts\python.exe -B -m afm_copilot.archive_organizer
```

Do not run flatten apply against the large archive before taking an independently verified backup.
The source must not change between preview and execution.

The explicit opt-in action is supported, but must first be tested against a disposable copied folder:

```powershell
.\.venv\Scripts\python.exe -B -m afm_copilot.archive_organizer --root C:\AFM_Test_Copy
```

The apply option uses --apply --confirm FLATTEN; do not use it until the
preview, backup and copy-test have been verified. It changes the filesystem
and can invalidate paths referenced by other software.

## Multichannel safeguards

Keep height/topography, amplitude, phase, deflection or feedback error,
current (c-AFM), potential (KPFM), frequency, dissipation, and unknown
instrument channels. The role classifier in afm_copilot.channels uses
titles and units conservatively and blocks height-only corrections on
non-height signals through afm_copilot.correction_gate.

## Required future scientific features

- Verify repeated acquisitions by comparing physically calibrated maps, not only filenames.
- Link distinct trace/retrace, channels and subsequent scans of the same area.
- Compare original/processed images with physical height/roughness/PSD/feature-preservation gates.
- Process huge archives with resume, per-file failure isolation and bounded resources.
- Never claim supervised accuracy on unlabeled new images without post-hoc ground truth.

Neither archive organizer nor correction gate currently processes a bulk collection of AFM images.