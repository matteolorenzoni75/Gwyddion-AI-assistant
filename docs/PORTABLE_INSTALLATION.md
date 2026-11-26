# Portable AFM Copilot workstation

The permanent Windows entrypoint is **AFM Copilot.bat**. **AFM_SETUP.cmd**
is the single installer/updater for this candidate branch. It uses the current
checkout, fetches a fast-forward update, preserves conflicting generated
launcher/ignore files privately and refuses unresolved source conflicts.
It does not move, delete, hash or copy the scientific archive.

## First use

- Run AFM_SETUP.cmd. On an existing workstation it reuses the one existing
  checkout and virtual environment. On an empty installation it needs Git,
  and can obtain Python 3.11 via winget if Python is missing.
- Python packages are installed by afm_copilot.bootstrap from pyproject.toml.
- Gwyddion with the 32-bit PyGwy module and its matching Python 2.7 interpreter
  are separate native prerequisites. Existing installations are reused.
- Use Impostazioni dati to choose the AFM data folder and optionally Learning.
  Settings live in the private profile, not in the repository.
- Subsequent launches use AFM Copilot.bat. Run Verifica installazione from the
  launcher for regression tests and a native synthetic plane-correction test.

The two current workstation roots need not be renamed or moved:
C:\AFM_Copilot is software; C:\AFM_Automation is the original archive.
The settings fallback recognizes both OLD input IMAGES and learning input data.
Existing private pair references are resolved only through known historic
prefixes and exact relative paths; ambiguous paths stay unresolved. It does
not match unrelated files with the same basename.

New GUI outputs are stored in separate workspace/runs/gui-* directories.
The existing private database and all old automatic derivatives remain intact.
Manual Gold Set accepts the existing anonymous pool and opens a selected working
copy in Gwyddion. Corrected references, no-change controls and rejected scans
are stored privately; exports use separate manifests. No training happens on
approval. The current bounded automatic comparison limit of 64 remains.

## Validation limits

The Python and GUI test suite runs in isolated local profile/data paths; GitHub
Windows CI does not test native PyGwy, which is checked on the workstation.
A real native smoke test is necessary before calling a release validated.
Do not interpret a mocked bridge test as verification of real AFM processing.
