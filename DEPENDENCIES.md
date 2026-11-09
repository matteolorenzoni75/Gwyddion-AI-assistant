# AFM Copilot — runtime and package dependencies

This file distinguishes three different things that are easy to confuse:

1. what a developer needs to run the project from source today;
2. what each optional application surface needs;
3. what the future Windows installer must contain so the end user installs
   nothing else.

## Supported development platform

| Component | Required version | Why |
|---|---:|---|
| Windows | 10 or 11, 64-bit | The desktop application and the legacy Gwyddion bridge are currently Windows-specific. |
| Python | 3.11, 64-bit recommended | The project metadata accepts Python 3.11 or newer, but 3.11 retains compatibility with the widest AFM Python ecosystem. Do not use the legacy Python 2.7 interpreter for the main application. |
| Git | Any current version, development only | Needed only to clone and develop the repository. It is not an end-user runtime dependency. |

Python 3.13 currently runs the tested core, but it is not the packaging target.
The distributable build should be produced and tested on Python 3.11.

## Python packages

These are declared in `pyproject.toml`; they should not be installed one by
one manually.

### Core library and command line

| Package | Minimum | Used for |
|---|---:|---|
| NumPy | 1.24 | Height arrays and numerical operations |
| SciPy | 1.10 | Filtering, connected components, signal and morphology operations |
| Matplotlib | 3.7 | AFM renders, reports and mask contact sheets |
| gwyfile | 0.3 | Reading and writing `.gwy`, including masks |
| Pillow | 10 | Raster image handling |
| igor2 | 0.5 | Reading Asylum/Igor metadata and scan notes |

Install the core only:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

### Desktop application

| Package | Minimum | Used for |
|---|---:|---|
| PySide6 | 6.6 | Windows application shell, panels and dialogs |
| pyqtgraph | 0.13 | Interactive AFM viewer, histogram, scale bar and profile ROI |

Install the desktop application:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gui]"
```

Launch it with `AFM Copilot.bat` or:

```powershell
.\.venv\Scripts\python.exe -m afm_copilot.gui
```

### Conversational/MCP interface

| Package | Minimum | Used for |
|---|---:|---|
| mcp | 1.0 | Exposes AFM inspection, planning and processing tools to an MCP client |

Install GUI and MCP together:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gui,mcp]"
```

Claude Desktop or another MCP client is optional and is not part of the AFM
Copilot package. The deterministic CLI and desktop viewer work without it.

### Development and tests

| Package | Minimum | Used for |
|---|---:|---|
| pytest | 8 | Automated regression suite |
| mcp | 1.0 | MCP tests import the server |

Install everything needed for development:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,gui,mcp]"
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Legacy Gwyddion runtime

Most recognition, measurement, masking, judgement and layout code is Python 3.
The following functions still require the legacy bridge:

- importing raw instrument formats into `.gwy`;
- running the reference Gwyddion processing functions and recipes;
- generating the independent Gwyddion grain-mask candidates;
- obtaining Gwyddion's automatic colour range where requested.

The bridge currently requires both:

| Component | Required build | Default location |
|---|---|---|
| Gwyddion | 2.70, **32-bit**, with `bin\gwy.pyd` | `C:\Program Files (x86)\Gwyddion` |
| Python | 2.7, **32-bit** | `C:\Python27\python.exe` |

The bitness must match. The 64-bit Gwyddion package does not provide the PyGwy
binding used by this project.

Non-default locations can be selected with:

```powershell
$env:GWYDDION_ROOT = "D:\private-runtime\Gwyddion"
$env:PYTHON27 = "D:\private-runtime\Python27\python.exe"
```

Verify the bridge with:

```powershell
.\.venv\Scripts\python.exe -m afm_copilot selftest
```

Without this legacy runtime, already converted `.gwy` files can still be read,
judged, measured, rendered and reviewed. Raw conversion and Gwyddion processing
are unavailable; the application must report this rather than silently skip
those stages.

## What the Windows installer must include

The intended end-user package must be self-contained. The user should not be
asked to install Python, run `pip`, edit `PATH`, or choose compatible DLLs.

The installer must contain:

- a private CPython 3.11 64-bit runtime;
- AFM Copilot and all core Python packages;
- PySide6, its required Qt plugins, and pyqtgraph;
- the `pygwy/` scripts and application assets;
- while the bridge remains necessary, a private pinned Gwyddion 2.70 32-bit
  and Python 2.7 32-bit runtime, subject to redistribution/licence review;
- internal configuration pointing to those private runtimes, without modifying
  the global system `PATH`;
- start-menu shortcuts, uninstaller, version information and code signature.

The installer must **not** contain:

- user scans, reports or training data;
- embedded OpenAI, Azure or other AI service keys;
- a dependency on Claude Desktop;
- assumptions about a pre-existing Python or Gwyddion installation.

AI credentials, if the future in-app AI layer uses a hosted model, must remain
behind an authenticated backend or in an administrator-managed secret store.

## Clean-machine acceptance test

“No ancillary installations” is achieved only when one installer passes all of
the following on clean Windows 10 and Windows 11 virtual machines:

1. install without Python, Gwyddion or developer tools already present;
2. launch from the Start menu;
3. import one raw AFM file and one `.gwy` file;
4. render and inspect the height map;
5. generate mask candidates and save an operator review;
6. run an allowed recipe and produce the audit/report;
7. restart and reload the saved review;
8. upgrade to a newer version without losing user configuration;
9. uninstall without removing user scientific data.

Until this matrix passes, the repository is a development installation, not a
redistributable Windows product.
