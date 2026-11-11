# Unified AFM Copilot workstation

Entry point: `C:\AFM_image_wizard\AFM Copilot.bat`.
The batch file starts the local PySide6 launcher with the project's Python 3
virtual environment, never the system's legacy Gwyddion Python 2.7.

## Integrated actions

- Main AFM Copilot GUI with scan viewer and Gwyddion recipes.
- Standalone Expert Labeler from launcher or main GUI Tools menu.
- Synoptic comparison GUI: ORIGINAL | OPERATOR-CORRECTED | AUTOMATIC.
  This view displays the three height maps, their RMS and range, and records
  one of five operator verdicts in a private local JSONL audit.
- Read-only discovery of older manually corrected originals: also handles
  names of the form `sample.ibw corrected with ...` and `sample corrected.tiff`.
  This is based on the existing `tools/collect_corrected_targets.py` logic;
  it finds candidate matches, not proven map equivalences.
- Recursive archive organizer preview (potentially slow): no move, delete or
  conversion during preview; do not run two copies simultaneously.
- Safe cache cleanup preview and opt-in cleanup of temporary Python/test caches.
- Git status and explicit push of **already committed** branch
  `dev/image-wizard` only. No automatic add/commit, no forced push, no
  remote deletion and no merge to main.

## Discover the user's older corrected images

```powershell
cd C:\AFM_image_wizard
.\.venv\Scripts\python.exe -B -m afm_copilot.manual_pairs
```

By default it visits known smaller local folders, NOT the huge archive that
may currently be undergoing a checksum inventory. To search a known folder:

```powershell
.\.venv\Scripts\python.exe -B -m afm_copilot.manual_pairs --root C:\AFM_Automation\corrected
```

Private details go to
`%USERPROFILE%\AFM_Copilot_Private_Audits\manual_comparisons\PRIVATE_manual_pair_candidates.json`.
Operator verdicts go into `PRIVATE_correction_verdicts.jsonl` in the same
private location. Neither path should be uploaded or committed.

Matches currently require a unique original in the **same directory**.
Matches across renamed files or different directories, and comparison of
actual calibrated arrays, remain an explicit next step. A manually corrected
version is never assumed better just because its name says corrected.

## Windows verification

```powershell
cd C:\AFM_image_wizard
git pull --ff-only origin dev/image-wizard
.\.venv\Scripts\python.exe -B -m pytest tests\test_manual_pairs.py tests\test_maintenance.py tests\test_channel_safety.py tests\test_correction_gate.py -q
.\.venv\Scripts\python.exe -B -m afm_copilot.manual_pairs
```

## Safety

The new modules do not move AFM originals, delete duplicate files,
rewrite corrected samples, train on operator validations or publish private
data. The GitHub changes are committed remotely to dev/image-wizard; after
git pull they are already on the user's computer, so a push will usually
report everything up to date.

Use the existing archive organizer ONLY in preview mode until an independently
verified backup and proper image similarity detection exist.

The comparison GUI is a human-review aid, not a substitute for verified
image-level matching. Non-topography channels are retained and not leveled.

## Remaining development

- Cross-directory original/manual/auto matching with calibrated image evidence.
- Read-only batch before/after QA with fixed color scale across columns.
- Channel-aware processing of amp/phase/error/current/potential with suitable
  numerical QA while keeping the primary cleaning work in topography.
- Clustering genuinely repeated scan acquisitions independently of file names.
- UI-led review and reversible relocation of archive files after backups.
## Launcher visual design (2026-11)

The primary window now presents two balanced, two-column sections of
compact icon cards: four **Analysis & validation** actions and six
**Archive & maintenance** actions. All cards show a one-line description
and an expandable `?` panel with the action's purpose and safety limits.
Actions include the existing main GUI, standalone Expert Labeler, synoptic
comparison, search for manual corrections, label audit, archive preview,
Git status, cache preview, safe cache cleanup and reviewed Git push.

An activity log remains visible at the bottom. The redesigned launcher
performs no automatic archive scan, cleanup, upload or background operation.
All buttons use the same actions and safety checks as before.

The latest manual-correction search on the operator's Windows machine
reported **8 candidate original/manual pairs among 328 scanned files**;
zero matching automated counterparts and no ambiguous pairs. These are
filename/adjacency matches and must still be validated by opening the
calibrated AFM images. No source material is modified by the search.

## Comparison viewer: instrument raw import fix

A real operator screenshot exposed an `AssertionError` while opening an
original `.ibw` in the three-way viewer. The viewer previously tried to
parse every file with `gwyfile` as GWY first, and on IBW this can raise
`AssertionError` before Gwyddion's instrument converter can run.

The corrected viewer sends raw IBW/TIFF/SPM directly through the existing
`GwyBridge` into its private temporary conversion directory. Files known
to be `.gwy` use the native GWY reader. Operator-corrected files with
unusual suffixes still attempt native GWY first, catching parser errors
and falling back to the bridge.

An unassociated automatic result is explicitly described as not paired,
not as a missing original. A new 'Associa risultato automatico...' button
lets the operator select an existing processed image; selection is checked
for readability and cannot point to the original or the manual target.
Accepted associations are saved to a private JSON manifest outside Git.

The eight manual/original pairs are preserved; no processed image is
created, inferred or silently fabricated by the association button.
Run `tests/test_compare_gui_import.py` on Windows to verify the import fix.

## Local directory organization and explicit paths

`AFM Copilot.bat` now shows a **DOVE SONO LE IMMAGINI** area with real
Windows locations, existence flags and buttons to open the containing folder:
the full AFM raw archive, the older testing/original directory, the older
GUI generated output location, the private manual-correction pair manifest,
the private expert-label SQLite and the project source checkout. It also
lists each distinct folder containing a discovered manual correction; this
list comes from the local PRIVATE pair manifest, not from GitHub.

To inspect the map without rescanning the full archive:

```powershell
.\.venv\Scripts\python.exe -B -m afm_copilot.directory_map
```

To create an EMPTY and separate workspace for future validated work:

```powershell
.\.venv\Scripts\python.exe -B -m afm_copilot.directory_map --prepare-workspace
```

The workspace lives at `C:\AFM_Automation\AFM_Copilot_Workspace` and has
four directories: `01_Manual_To_Review`, `02_Automatic_Results`,
`03_Approved`, `04_Reports`. This command only creates empty directories.
It does not relocate manual corrections, create new automatic scans,
delete duplicate files, rename or flatten the 97,082-file raw archive,
or alter the existing private label database. It is safe to rerun.

The detailed JSON directory map is private at
`%USERPROFILE%\AFM_Copilot_Private_Audits\directory_map\PRIVATE_locations.json`.

The comparison viewer also fixes a small test/status mismatch by reporting
`Automatic output not yet associated` when no automated image was linked.
This distinguishes a missing association from a missing raw file.

Windows verification:

```powershell
cd C:\AFM_image_wizard
git pull --ff-only origin dev/image-wizard
.\.venv\Scripts\python.exe -B -m pytest tests\test_compare_gui_import.py tests\test_directory_map.py tests\test_workstation_launcher.py -q
.\.venv\Scripts\python.exe -B -m afm_copilot.directory_map --prepare-workspace
```

## Launcher layout adjustment

The launcher header now identifies the processing engine as
**Gwyddion 32-bit | PyGwy (Python 2.7)**, alongside the native icon
extracted from the locally installed Gwyddion executable. If the
executable cannot be located, the program uses the standard application
icon rather than inventing an official logo.

The image directory list is moved below all action cards, just above
the activity log. It displays only the user-facing directories for
the full AFM archive, historic raw scans, older processed GUI images,
new automatically processed and approved workspace results, plus
the actual discovered folders of manual corrections. The code checkout,
private SQLite database, private manifest file and generic workspace
container are intentionally omitted from the launcher display.

The previous descriptive tagline has been removed. Buttons and
workflows otherwise remain the same. No original scan is moved.

## Generate provisional automatic corrections for known manual comparison scans

The synoptic GUI now has **Genera correzioni AFM Copilot**. After explicit
confirmation, it launches `afm_copilot.auto_compare` on the private
original/manual candidate manifest (up to **16** pairs; typically 8).
It does NOT touch the entire 97,082-file AFM archive.

Each original is imported through Gwyddion 32-bit / PyGwy and the height
channel is extracted into a separate local working document. Any source
phase, amplitude, error, current, potential and trace/retrace channels remain
unchanged in the original file. `decide.plan_for`, `quality.assess` and
`correction_gate.gate_recipe` select **only** operations marked `safe_auto`.
Potentially destructive scar, nonlinear background, mask/interpolation or
poor-calibration operations are held; the output is a PROVISIONAL review
candidate, not necessarily a fully repaired scan.

Each output is placed under
`C:\AFM_Automation\AFM_Copilot_Workspace\02_Automatic_Results\<private-id>\corrected\height.gwy`.
Separate directories prevent collisions and existing outputs are never
overwritten. The per-pair association is saved only in the private
`PRIVATE_manual_pair_candidates.json`; the private audit is
`PRIVATE_automatic_correction_audit.jsonl`. Original and manual images
are never rewritten, and no model is trained or automatically approved.

When the batch finishes the synoptic viewer reloads the saved third-column
associations. A strong change in RMS, failed Gwyddion step, invalid physical
unit, geometry mismatch or questionable quality suspends the candidate
rather than silently presenting it as correct.

Direct Windows command (only on the operator PC):

```powershell
cd C:\AFM_image_wizard
git pull --ff-only origin dev/image-wizard
.\.venv\Scripts\python.exe -B -m pytest tests\test_auto_compare.py tests\test_compare_gui_import.py -q
.\.venv\Scripts\python.exe -B -m afm_copilot.auto_compare --confirm RUN_8_CANDIDATES
```

Do not start the same batch twice simultaneously. It is limited to the
manually associated pairs, not to an unbounded directory discovery. Any
correction shown in the viewer requires visual expert validation.
