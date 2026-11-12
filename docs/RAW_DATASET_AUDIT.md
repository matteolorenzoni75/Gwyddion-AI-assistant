# External raw TIFF / Igor Binary dataset: local-only audit

The only source of original AFM scans for the Windows workstation is
`C:\AFM_Automation\OLD input IMAGES`, including its subfolders. Never move the
files into this public repository. `C:\AFM_image_wizard` is the working checkout.

## Run

In PowerShell, from the working checkout (with Python environment installed):

```powershell
Set-Location C:\AFM_image_wizard
.\.venv\Scripts\python.exe tools\audit_raw_dataset.py
```

The user confirms that the evaluation set comprises **244 images**. The
previous raw instrument inventory found **268 files** (194 TIFF and 74 IBW).
These count different things; do not infer that all 268 belong to the
evaluation set, or that the difference of 24 represents duplicates.
The training code excludes the entire raw archive conservatively, pending an
explicitly approved and separately sourced training set.

The script walks all `.ibw`, `.tif`, `.tiff` files recursively, checks whether
multiple files would convert to the same `<stem>.gwy`, identifies byte-for-byte duplicates using private SHA-256 values (which do not leave the PC), reads only the **presence**
of Igor notes, and uses the installed Gwyddion 2.70/PyGwy bridge for read-only
channel and calibration assessment. No pixels are changed, converted, copied or
uploaded. Gwyddion availability is reported separately from a passing audit.

Test the first 10 files without opening Gwyddion:

```powershell
.\.venv\Scripts\python.exe tools\audit_raw_dataset.py --max-files 10 --inventory-only
```

Reports are written by default to
`%USERPROFILE%\AFM_Copilot_Private_Audits\<timestamp>`, outside Git:

- `PRIVATE_manifest.csv`: private IDs, original filenames, SHA-256 checksums and
  paths. **Keep locally, never upload**.
- `PRIVATE_probe_job.json`: local job paths used for the read-only importer.
  **Keep locally, never upload**.
- `CHATGPT_REVIEW.zip`: anonymous counts, channel types, calibration flags,
  dimensions and trace/retrace observations. **This is the only file to upload
  to ChatGPT.** It does not contain sample names or raw images.

A checksum match only establishes identical file bytes. TIFF and IBW encodings of the same measurement may differ, and unrelated scans can share a basename. **The count of unique bytes is not the count of independently evaluated AFM images.**

A Gwyddion success proves the importer could read the channels and their units;
it does *not* independently prove the instrument calibration was correct. No
recipe selection or artifact classification is made from filenames.

The current batch conversion uses stem-only output names; **do not run a bulk
conversion until basename collisions reported by this audit are resolved**.
