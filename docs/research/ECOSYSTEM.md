# Ecosystem survey — what to build on

Library, tooling and integration findings. Sources in [SOURCES.md](SOURCES.md).
Items marked **VERIFIED HERE** were tested directly against the Gwyddion 2.70
install on this machine.

---

## 1. Headline integration facts

### 1.1 There is no `--script` flag. There never was. ✅ VERIFIED HERE

Every `--option` string was extracted from the actual `gwyddion.exe` binary.
The complete set is:

```
--check          --class           --convert-to-gwy   --debug-objects
--disable-gl     --disable-modules --display          --gtk-module
--help           --identify        --log-to-console   --log-to-file
--name           --new-instance    --no-log-to-console --no-log-to-file
--no-splash      --param           --remote-existing  --remote-new
--remote-query   --screen          --startup-time     --sync
--version
```

**No `--script`. No `--script-file`. No `--run-script`. No Python flag of any
kind.** The old `AFM_Automation` code disagreed with itself about which of the
three to use; all three were wrong, and no amount of flag-fixing would have
worked.

### 1.2 You don't need `gwyddion.exe` at all ✅ VERIFIED HERE

Gwyddion ships a standalone Python extension, `bin/gwy.pyd`. It imports from a
plain Python 2.7 interpreter and **registers all process modules automatically
on import** — no init call, no GUI, no display.

Verified end-to-end: constructed a tilted `DataField`, ran
`gwy_process_func_run('level', ...)`, and the plane was removed (height range
5.04e-08 → 4.4e-22).

Working recipe — this is what [`tools/run_py27.ps1`](../../tools/run_py27.ps1)
automates:

```
PATH       = C:\Program Files (x86)\Gwyddion\bin;%PATH%
PYTHONPATH = C:\Program Files (x86)\Gwyddion\bin;
             C:\Program Files (x86)\Gwyddion\share\gwyddion\pygwy
C:\Python27\python.exe your_script.py
```

Expect three harmless `GType ... as enum when in fact it is of type GFlags`
warnings on stderr. They are GLib type-system noise, not errors.

### 1.3 Measured API surface ✅ VERIFIED HERE

From [`tools/introspect_pygwy.py`](../../tools/introspect_pygwy.py):

| Category | Count |
|---|---|
| Process functions (Data Process menu) | **197** |
| File functions (import/export formats) | **176** |
| Classes | 141 |
| Module-level functions | 489 |
| Constants | 499 |
| Methods on `DataField` alone | 395 |

Full inventory: [`docs/pygwy_api/PYGWY_API.md`](../pygwy_api/PYGWY_API.md).

Two immediately useful corrections to assumptions in the old code:

- The plane-levelling function is named **`level`**, not `plane_level`.
  `gwy_process_func_exists("plane_level")` returns **False**.
- `gwy_process_func_get_menu_path()` and `get_tooltip()` work for every
  function, which means **the tool catalogue for the LLM can be generated
  automatically from the library itself**, and the menu path supplies a free
  semantic hierarchy (`/Level/Flatten Base`, `/Correct Data/Remove Scars`).

### 1.4 Windows deployment constraint

**PyGwy is supported only in the 32-bit Windows packages.** The 64-bit
executables have no Python scripting support at all. The 32-bit build also needs
a separate Python 2.7 + PyGTK2 + PyCairo + PyGObject install, and if they are
absent **pygwy silently fails to register rather than erroring**.

This machine is correctly configured. Any deployment elsewhere inherits the
whole fragile chain — which is a first-class argument for minimising PyGwy's
role rather than building everything on it.

### 1.5 Gwyddion 3 is the eventual exit from Python 2.7 — but not yet

Gwyddion 2.x will never get Python 3 bindings; the blocker is architectural
(the `gwy` module is bound through pygtk2, a Python-2-only technology).

Gwyddion 3 is real and moving: **3.4 (June 2025) added initial
gobject-introspection support**, and **3.11 "Dogfood" (June 2026) marks the
point where the developers switched to v3 for their own daily work**.

But: **there are no Windows builds of Gwyddion 3**, it is explicitly "not yet
meant for general use", and the completeness of the GI annotations for the
*module* system (as opposed to the libraries) could not be verified. Track it;
do not plan around it for 12–24 months.

---

## 2. Python 3 can read all of this project's data

**Yes — without Gwyddion.** This is the finding that lets the modern layer be
independent.

| Library | Formats | Writes `.gwy`? | License | Status |
|---|---|---|---|---|
| **`gwyfile`** | `.gwy` | ✅ **yes** | MIT | Active but quiet; single maintainer |
| **`igor2`** | `.ibw`, `.pxp` | — | LGPL-3 | Actively maintained; best `.ibw` reader |
| **`AFMReader`** | `.ibw .spm .jpk .gwy .asd .top` | — | GPL/LGPL (inconsistent) | Active, young; has the Asylum-specific glue |
| **`tifffile`** | TIFF | — | BSD-3 | Very active |
| `pySPM` | Bruker `.spm`, Nanonis `.sxm` | — | Apache-2.0 | Active; also a processing library |

`AFMReader`'s `ibw.py` does exactly the Asylum-specific work otherwise needing
reverse-engineering: splits the wave note into a key:value dict, decodes
`wave["labels"]` to find the named channel (e.g. `HeightRetrace`), reads
`SlowScanSize`/`FastScanSize` for nm-per-pixel, applies `np.flipud`, scales
m→nm.

⚠️ **Open question about the `.tiff` inputs.** Asylum documentation frames TIFF
export as an image-export convenience. **Assume the TIFFs are rendered pictures
without physical z-calibration until proven otherwise**, and treat `.ibw` as the
source of truth. This needs checking against the actual files before any
metrology claim is made from a TIFF.

**Negative findings worth recording:** RosettaSciIO/HyperSpy has **no** `.ibw`
and **no** `.gwy` reader — do not plan around it. PyPI `nanoscope` is stale
(2023, caps at Python 3.11.4). There is no project called `nanoscope-tools`.
`pyGSF` is a name trap — every GitHub `pygsf` is sonar/bathymetry; the Gwyddion
Simple Field library is **`gsffile`**.

---

## 3. Python 3 processing packages

### TopoStats — the most instructive package in the survey

GPL-3.0 · active (2026-08) · **`requires_python >=3.10,<3.12`**

**TopoStats used to be a PyGwy application.** Its `legacy` branch still contains
`pygwytracing.py`, which drove Gwyddion's `flatten base` and `mask_outliers`
through pygwy. **The team then rewrote the whole thing in pure Python 3 on
numpy/scipy/scikit-image and abandoned pygwy.** That is exactly the migration
this project is contemplating, executed by a funded academic group over several
years. Read `pygwytracing.py` before designing the PyGwy layer.

Its flattening pipeline is staged and mask-aware: `median_flatten()` →
`remove_tilt()` → `remove_quadratic()` → `remove_nonlinear_polynomial()` →
`average_background()`. Crucially **it runs twice**: once unmasked for a rough
level, then a mask is computed and the same corrections re-run *ignoring masked
pixels*. Same idea as Gwyddion's `flatten_base`, but transparent and hackable.

Its `scars.py` is a genuine reimplementation of Gwyddion's scar algorithm:
mark → spread from high-confidence seeds → drop runs shorter than
`min_scar_length` → linear interpolation across the scar → repeat (2 passes).

⚠️ Caveats: the `<3.12` pin; heavy dependencies (TensorFlow + Keras, topoly,
skan); tuned for DNA/protein on flat mica, so grain assumptions may not transfer
to arbitrary materials surfaces; GPL-3.0-only.

### SPIEPy — small, BSD, and does the one thing that matters most

BSD-2-Clause · Python ≥3.8 · last release 2023 · **no public source repo**
(source ships only in the PyPI sdist; docs on a university webspace page)

`flatten_by_iterate_mask()` is the flagship: loops flatten → mask → flatten
until the mask stops changing by more than N pixels, returning both the
corrected image and the subtracted plane. Also `flatten_by_peaks()` (fits the
polynomial plane **only to image peaks**, for adsorbate-covered surfaces),
`mask_by_troughs_and_peaks()`, `locate_steps()` (Canny-based step-edge
detection), `measure_feature_properties()`.

⚠️ Treat as frozen: one academic author, no issue tracker, no repository.
**Recommendation: vendor the handful of functions needed rather than depend on
it.** Its documented heuristic is worth encoding regardless: *for images with
step edges, use only first-order planes, because higher-order polynomials will
try to fit the step itself.*

### Destriping — a rich, transferable field

Direct AFM implementations: TopoStats `scars.py` (GPL-3), pySPM
`filter_scars_removal()` (Apache-2.0), spym `destripe()` (MIT), and Gwyddion's
own `scars_remove` / `align_rows` / `laplace`.

Cross-domain, and **directly transferable** — AFM scan-line artifacts are
geometrically the same problem as light-sheet and satellite striping:

- **`pystripe`** (MIT, from light-sheet microscopy) — **wavelet-FFT
  deconvolution along the stripe direction**, the standard Münch et al. method.
  One-line use: `pystripe.filter_streaks(img, sigma=[128,256], level=7,
  wavelet='db2')`. Small, pure numpy + PyWavelets, low porting risk.
  **Strongest single recommendation here.**
- Remote-sensing literature on directional ℓ0 sparse modelling and image
  decomposition frames destriping as *separating a low-rank/directional stripe
  component from the scene* — more principled than threshold-and-interpolate,
  and it handles gradual row offsets that scar filters miss.

### Tip deconvolution — the strongest reason to keep PyGwy

❌ **No maintained pure-Python-3 blind tip reconstruction library exists.**
The state-of-the-art differentiable BTR implementation is **written in Julia**.

✅ **Gwyddion has it, and it is exposed through PyGwy** (verified here):
`gwy_tip_estimate_full`, `gwy_tip_estimate_partial` (Villarrubia BTR),
`gwy_tip_dilation`, `gwy_tip_erosion`, `gwy_tip_cmap` (certainty map), plus 7
parametric tip presets.

Reimplementing Villarrubia BTR is a week of work and a correctness risk.
**This capability alone justifies the Python 2.7 bridge.**

---

## 4. Gwyddion automation prior art — thin

| Repo | What | Assessment |
|---|---|---|
| `onakanob/PyGwyBatch` | Minimal Py3→Py2 bridge (Py3 orchestrator → Py2 script) | MIT, 3 stars, 8 commits. Naive — the channel is a single string — but validates the pattern |
| `emmegamma/PyGwy-repo` | Curated script collection + link hub | MIT. Best entry point for finding other PyGwy code |
| `AFM-SPM/TopoStats @ legacy` | `pygwytracing.py` | **The most instructive artifact in the survey** — a real pipeline *and* the record of a team leaving PyGwy |

**Honest summary: nobody has built a proper Python-3-orchestrated Gwyddion
service.** There is no `pygwy-rpc`, no Gwyddion REST server, no maintained
bridge, and **no Gwyddion MCP server**. That is both the opportunity and the
warning.

---

## 5. GUI recommendation: PySide6 + pyqtgraph, on Python 3.11

**Target Python 3.11, not 3.13.** TopoStats (`<3.12`), pySPM-on-PyPI (`<3.13`),
AFMReader (via pySPM) and napari-AFMReader (3.10/3.11) all cap below 3.13.
3.11 gets the entire AFM ecosystem; 3.13 gets almost none of it.

| Option | Verdict |
|---|---|
| **PySide6 + pyqtgraph** | **★ Recommended** |
| napari | Best-in-class viewer, awkward as an app shell |
| Dear PyGui | Fast and easy to package, but no scientific image widget and cannot embed matplotlib |
| Local web (FastAPI+React) | Highest total cost; only if remote access matters |

Reasoning, in priority order:

1. **Licensing.** PySide6 is LGPL and pyqtgraph is MIT — the only combination
   that leaves licensing options fully open. (PyQt6 is GPL/commercial only.)
2. **Every required feature is native**: `ImageItem` + `ColorBarItem` +
   `HistogramLUTWidget` give the AFM viewer idiom (image, colormap, and a
   draggable histogram for interactive z-range clipping); `ROI` classes give
   line profiles and region selection; stacked semi-transparent `ImageItem`s
   give mask overlays; `GLSurfacePlotItem` gives an OpenGL 3D surface view close
   to Gwyddion's own; matplotlib embeds via `FigureCanvasQTAgg`.
3. **Windows packaging is a solved, boring problem.** Given this app already
   carries a fragile 32-bit-Gwyddion + Python-2.7 + PyGTK2 chain, **the GUI must
   not add a second hard packaging problem.** This settles it against napari,
   which now builds installers via conda-standalone + constructor.
4. Lowest migration cost from the existing Tkinter GUI.

**napari is genuinely tempting** — its `Labels` layer *is* a mask overlay with
picking and editing, and **`napari-AFMReader` already handles this project's
exact file set today** (`.ibw`, `.gwy`, `.spm`, `.jpk`, …). Sensible compromise:
build in PySide6, offer "Open in napari" as a power-user button.

---

## 6. LLM layer — the scale problem and the answer

Gwyddion exposes 489 module functions + 395 `DataField` methods. **You cannot
put that in a tool schema.** Models degrade well before a few hundred tools.

The consensus answer is a **two-tier design**:

1. **10–30 hand-curated, typed, semantically meaningful tools** —
   `flatten(method, mask_strategy)`, `remove_scars(threshold, max_width)`,
   `level_rows(mode)`, `detect_artifacts()`, `deconvolve_tip(...)`. Each wraps
   one or several Gwyddion calls with sane defaults and units.
2. **A retrieval/discovery tool over the full API** —
   `search_gwyddion_functions(query)` returning name + menu path + tooltip,
   **auto-generated from the inventory this project already produced**, plus a
   validated snippet-execution escape hatch.

### What the literature says about LLM agents at instruments

**AILA / AFMBench (Nature Communications, 2025)** — the closest published work,
benchmarking LLM agents on real AFM tasks. Findings that must shape the design:

- **Multi-agent substantially outperforms single-agent**, especially on
  multi-tool tasks.
- **Domain QA competence does not transfer to agentic competence.** Do not pick
  a model on benchmark knowledge scores.
- **Severe prompt fragility** — slight prompt-structure changes cause
  substantial performance variation. Pin and regression-test prompts.
- **"Sleepwalking"** — agents deviate from instructions in ways that raise
  safety concerns.

**Biswas et al. (IEEE OJIM, 2025)** — a vision model classifies AFM defects, an
LLM explains and advises. 91.4% overall accuracy; **93% recall for tip
contamination, but only 60% for "not tracking"**. Note that "not tracking" is
also the class that is *not post-processable*, so a wrong answer there costs the
user the most.

**arXiv:2602.04051** (same group) — the full pipeline: ResNet-18 classifier →
lightweight segmentation (IoU 0.72) → **"Smart Flatten"**, a mask-aware per-line
polynomial fit using **only unmasked pixels**. Reported line-wise residuals
**49.5 ± 63.7 nm vs 135.7 ± 188.3 nm** for conventional global polynomial
fitting. **That 2.7× improvement is the strongest quantitative argument in the
literature for detect-then-correct over correct-blindly — and it validates
putting segmentation *before* flattening.**

### The critical architectural lesson

**Do not ask a VLM to see the artifact.**

Every AFM system that classifies artifacts well uses a trained
convolutional/transformer vision head, not a general VLM's visual reasoning.
In CT imaging, **IQAGPT** showed that a fine-tuned small quality-captioning
vision model feeding an LLM **beat both GPT-4 and the pure vision model**.
Biswas et al. converged on the same split independently.

So: **detectors produce numbers and named findings; the LLM reasons, sequences,
explains, and negotiates with the user.**

### Closest architectural prior art

**Omega** (Nature Methods, 2024) — an LLM conversational agent as a **napari
plug-in** that performs image-processing tasks, corrects its own coding
mistakes, and visually interprets viewer contents. It solved the same problem
(natural language → image-analysis operations in a host application) one
ecosystem over. **Read its design before finalising this one.**

---

## 7. What has *not* been demonstrated — i.e. what is novel here

- A VLM directly recognising AFM artifacts from a height map, with published
  accuracy. **No benchmark of frontier VLMs on AFM artifact recognition exists
  at all.**
- **Closed-loop LLM-driven post-processing** — recognise artifacts, select
  corrections, apply via an analysis package's API, score, iterate. Nobody has
  published this for SPM.
- Automatic discrimination of genuine periodic sample structure from periodic
  noise in AFM.
- Automatic stripe-orientation detection at arbitrary angles in AFM (solved in
  remote sensing, not transferred).
- A Gwyddion MCP server.
