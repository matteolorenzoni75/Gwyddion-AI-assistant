# AFM Copilot

An interactive application with an LLM at its core that reads an AFM height map,
recognises what the artifacts are, and drives Gwyddion's own processing
functions to correct them — with as little human effort as possible.

**Status: research and groundwork complete. No application code yet.**
The only working code here is the PyGwy inventory tooling in [`tools/`](tools/).

This project continues [`C:\AFM_Automation`](file:///C:/AFM_Automation), which is
untouched. Nothing there has been modified or deleted.

---

## What's here

| Path | What it is |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | The proposed four-layer design, pipeline order, masking plan, safety rules |
| [`docs/research/ARTIFACT_TAXONOMY.md`](docs/research/ARTIFACT_TAXONOMY.md) | **The recognition target list** — every artifact class, its signature, detection and whether it is correctable at all |
| [`docs/research/QUALITY_METRICS.md`](docs/research/QUALITY_METRICS.md) | How to score a correction without fooling yourself |
| [`docs/research/ECOSYSTEM.md`](docs/research/ECOSYSTEM.md) | Library survey, Gwyddion integration facts, GUI and LLM-layer decisions |
| [`docs/research/SOURCES.md`](docs/research/SOURCES.md) | Every reference, with the paywalled ones flagged |
| [`docs/pygwy_api/PYGWY_API.md`](docs/pygwy_api/PYGWY_API.md) | **Complete verified inventory of the PyGwy API on this machine** |
| [`docs/pygwy_api/pygwy_api.json`](docs/pygwy_api/pygwy_api.json) | The same, machine-readable |
| [`docs/data_survey/FINDINGS.md`](docs/data_survey/FINDINGS.md) | **What the real files actually contain** — channels, calibration, metadata |
| [`tools/introspect_pygwy.py`](tools/introspect_pygwy.py) | Regenerates the API inventory (Python 2.7) |
| [`tools/query_api.py`](tools/query_api.py) | Search/browse the inventory |
| [`tools/survey_channels.py`](tools/survey_channels.py) | Reports channels + metadata in a folder of raw files |
| [`tools/make_dataset.py`](tools/make_dataset.py) | **Generates labelled training data with exact ground truth** |
| [`tools/run_py27.ps1`](tools/run_py27.ps1) | Runs a PyGwy script headlessly |

---

## Using it

Set up once:

```bash
C:\Users\MLorenzoni\AppData\Local\Programs\Python\Python313\python.exe -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -e .
```

Check that Gwyddion can be driven headlessly:

```bash
.venv\Scripts\python.exe -m afm_copilot selftest
```

**See what the one-click recipes do, and why:**

```bash
.venv\Scripts\python.exe -m afm_copilot recipes
```

```bash
.venv\Scripts\python.exe -m afm_copilot recipes clean-with-features
```

**Process a folder** — raw instrument files are converted automatically. Every
step reports what it changed, so the processing is auditable rather than a
black box:

```bash
.venv\Scripts\python.exe -m afm_copilot process "D:\scans" --recipe quick-clean --out results
```

**Render a batch as comparable images** — one shared colour scale, scale bar,
fixed DPI. `--auto-group` splits a mixed folder into scale groups so shallow
scans are not flattened by deep ones:

```bash
.venv\Scripts\python.exe -m afm_copilot batch-images "D:\scans" --out figures --dpi 300 --auto-group
```

## The API inventory

Gwyddion's processing power is the point of this project, and the inventory is
how we stop guessing at it. Every name below was **confirmed by calling the live
API** (`gwy_process_func_exists`), not read from documentation:

| Category | Count |
|---|---|
| Process functions | **197** |
| File functions (formats) | **176** |
| Classes | 141 |
| Module functions | 489 |
| Methods on `DataField` alone | 395 |

Browse it:

```bash
C:\Python27\python.exe tools\query_api.py
```

```bash
C:\Python27\python.exe tools\query_api.py --search flatten
```

```bash
C:\Python27\python.exe tools\query_api.py "_Correct Data"
```

Regenerate it after a Gwyddion upgrade:

```bash
powershell -ExecutionPolicy Bypass -File tools\run_py27.ps1 tools\introspect_pygwy.py
```

---

## Two facts that change everything

**1. There is no `--script` flag.** Every `--option` string was extracted from
`gwyddion.exe`. `--script`, `--script-file` and `--run-script` all do not exist.
The old project's code disagreed with itself about which to use; all three were
wrong.

**2. You don't need `gwyddion.exe` at all.** `bin/gwy.pyd` imports from a plain
Python 2.7 interpreter and registers every process module automatically. Verified
end-to-end: a tilted field went through `gwy_process_func_run('level', ...)` and
the plane was removed — no GUI, no display, no flags.

That is what `tools/run_py27.ps1` sets up.

---

## Environment

| Component | Path | Note |
|---|---|---|
| Gwyddion 2.70 **32-bit** | `C:\Program Files (x86)\Gwyddion` | PyGwy exists **only** in 32-bit builds |
| Python 2.7.16 (32-bit) | `C:\Python27` | For PyGwy only |
| Python 3 | (to be created) | **Target 3.11**, not 3.13 — see below |

**Why Python 3.11:** TopoStats (`<3.12`), pySPM on PyPI (`<3.13`), AFMReader and
napari-AFMReader all cap below 3.13. 3.11 gets the whole AFM ecosystem; 3.13
gets almost none of it.

Override the defaults with the `GWYDDION_ROOT` and `PYTHON27` environment
variables if either moves.

---

## Non-negotiables for this codebase

1. **PyGwy scripts are Python 2.7.** No f-strings, no `pathlib`, no type hints,
   no `dataclasses`, no walrus, no `exist_ok=`/`capture_output=`.
   `import gwy` at the top of a file means Python 2.7.
2. **Small patches, never rewrites.** A previous refactor on the old project
   replaced working scripts with stubs and destroyed functionality.
3. **Refusal is a valid answer.** Not-tracking, charging, double tip and moiré
   are not correctable in post-processing. Saying so is the right output.
4. **Do not minimise RMS roughness.** Every levelling step biases Sq downward by
   a calculable amount; an optimiser that chases low Sq destroys real
   morphology. See [QUALITY_METRICS.md](docs/research/QUALITY_METRICS.md).

---

## The training data problem, and how it is solved

14 real images is not a dataset. `tools/make_dataset.py` generates as many
labelled samples as you want, with **exact** ground truth — clean and degraded
`.gwy` pairs plus a labels row recording every artifact applied and its
parameters.

```bash
powershell -File tools\run_py27.ps1 tools\make_dataset.py --n 500 --size 256 --out data\synthetic_v1
```

`data/synthetic_v1/` holds a first run: 500 samples, six surface classes, seven
independently-applied artifact types. Labels and summary are tracked in git; the
`.gwy` pixels are not, because they regenerate exactly from the recorded seed.

The point of it is the label no real dataset has: **`has_real_periodicity`**.
Surfaces of kind `grating` and `lattice` carry genuine periodic structure; the
`hum` artifact adds fake periodicity at an arbitrary angle. 81 samples in the
first run have **both at once** — in one case a real lattice at 157.3° against
periodic noise at 155.1°, 2.2° apart. Telling those two apart is the hardest
unsolved problem in the AFM literature, and this is supervision for it.

Synthetic data does not replace real images; it makes the detectors trainable
and testable before they ever touch a real one.

## Next steps

1. Create the Python 3.11 environment; confirm `igor2` reads the `.ibw` files.
2. Prototype the PyGwy bridge (`.gwy` in, JSON out) and soak-test repeated
   subprocess spawning.
3. Build the detector bank against `data/synthetic_v1`, where the answers are
   known.
4. Only then the GUI, and only then the LLM layer.

**Also worth doing at the instrument, not in code:** configure the Asylum
software to save **both** scan directions for the height channel. See
[FINDINGS.md §1](docs/data_survey/FINDINGS.md) — it costs nothing at
acquisition and unlocks detectors that post-processing cannot substitute for.
