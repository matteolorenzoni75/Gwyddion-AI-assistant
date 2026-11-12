# Windows packaging target

The distributable product is **one signed installer for a clean Windows 10 or
11 PC**.  The user must not install Python, create a virtual environment, edit
`PATH`, or discover compatible library versions.

This is a target, not the current state.  Today the application still depends
on a project virtual environment and on the legacy Gwyddion 2.70 32-bit /
Python 2.7 32-bit bridge.

## Acceptance criteria

- Per-user installer and uninstaller; administrator rights are not required
  unless a future driver genuinely needs them.
- Start-menu shortcut and file/folder picker.  No command prompt is required.
- Private Python 3.11 runtime with PySide6 and the scientific dependencies.
- No reliance on a system Python installation or on global environment
  variables.
- Gwyddion/Python 2.7, while still required, is installed as a private runtime
  addressed by paths internal to the application.  It must not replace or
  modify another Gwyddion installation on the PC.
- User reviews and configuration live under the user's application-data
  directory; scientific outputs go only where the user selected.
- AI credentials are never embedded in the executable.  A deployed AI layer
  uses an authenticated backend or an administrator-managed secret store.
- The build is signed and tested end to end on clean Windows 10 and Windows 11
  virtual machines, both with and without a pre-existing Gwyddion install.
- Installation, first launch, raw-file import, review, processing, report
  generation, update and uninstall all have automated smoke checks.

## Proposed build path

1. Rebuild and pin the application on Python 3.11.  The current development
   environment is Python 3.13, while several useful AFM libraries still stop at
   3.11.
2. Produce a PyInstaller **onedir** build.  It is easier to inspect, update and
   debug than a large self-extracting onefile executable and avoids repeated
   extraction at every start.
3. Inventory the exact DLLs, modules, fonts and Qt plugins loaded on a clean
   machine.  Add explicit collection rules only for resources actually used.
4. Decide the legacy-runtime strategy:
   - short term: redistribute a private, pinned Gwyddion 2.70 32-bit and
     Python 2.7 32-bit runtime after confirming licences and required DLLs;
   - long term: move reference operations to maintained Python 3 libraries or
     a supported Gwyddion integration and remove the legacy bridge.
5. Wrap the onedir application and private runtimes with Inno Setup or WiX,
   using internal relative paths for `GWYDDION_ROOT` and `PYTHON27`.
6. Add code signing, versioned upgrades and a clean rollback/uninstall path.

## Main risk

PySide6 itself is a routine Windows packaging problem.  The difficult part is
the mixed-bitness legacy chain: a 64-bit Python 3 GUI driving 32-bit Gwyddion
through a 32-bit Python 2.7 subprocess.  Claiming “no ancillary installations”
is justified only after that entire chain is bundled and exercised on clean
machines, or removed.
