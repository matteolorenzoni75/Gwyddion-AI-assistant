# Proposed architecture

Status: **proposal, not yet built.** Nothing here is implemented except the
PyGwy inventory tooling in [`tools/`](../tools/).

The design follows from three findings in the research
([ECOSYSTEM.md](research/ECOSYSTEM.md), [QUALITY_METRICS.md](research/QUALITY_METRICS.md)):

1. Python 3 can read every file format this project uses, so the Python 2.7
   boundary can be pushed back to "execute Gwyddion algorithms" only.
2. A trained vision head plus classical detectors beats a general VLM at seeing
   artifacts; the LLM's job is reasoning and sequencing, not perception.
3. Minimising RMS roughness is an actively wrong objective. The scorer has to be
   built on PSD bands, anisotropy and feature preservation instead.

---

## Four layers

```
┌──────────────────────────────────────────────────────────────┐
│  4. LLM decision layer            (Python 3.11)              │
│     planner / executor / verifier roles                      │
│     ~20 curated typed tools + API search over 197 functions  │
│     never emits raw parameters -- selects bounded operations  │
└───────────────┬──────────────────────────────────────────────┘
                │  named findings + numbers (never raw images)
┌───────────────┴──────────────────────────────────────────────┐
│  3. Detector bank + scorer        (Python 3.11)              │
│     classical: PSD bands, Str, row-difference stats,         │
│       Ssk/Sku/Sz triage, FFT peak significance,              │
│       stripe angle via structure tensor, certainty map       │
│     learned: small head for tip contamination / not-tracking │
│     scorer: PSD-band + Str + Sdq + bias-corrected Sq         │
└───────────────┬──────────────────────────────────────────────┘
                │  numpy arrays
┌───────────────┴──────────────────────────────────────────────┐
│  2. Processing            (hybrid -- the key decision)       │
│     Python 3 in-process: levelling, row alignment, poly,     │
│       destriping (LRR, pystripe), masking, grain stats       │
│     PyGwy subprocess: blind tip reconstruction, certainty    │
│       map, exotic importers, bit-identical Gwyddion results  │
└───────────────┬──────────────────────────────────────────────┘
                │  .gwy via gwyfile, or .gsf via gsffile
┌───────────────┴──────────────────────────────────────────────┐
│  1. I/O + GUI                     (Python 3.11, PySide6)     │
│     igor2 (.ibw) / tifffile (.tiff) / gwyfile (.gwy r+w)     │
│     pyqtgraph: colormap, histogram-LUT, mask overlay,        │
│       ROI profiles, OpenGL 3D surface                        │
│     never touches Python 2.7                                 │
└──────────────────────────────────────────────────────────────┘
```

### Why hybrid processing rather than all-PyGwy

Routine corrections in Python 3 give **instant interactive previews with no
subprocess latency**, and remove the 32-bit-Gwyddion + Python-2.7 + PyGTK2
dependency chain from the common path. PyGwy is reserved for what Python 3
genuinely lacks — above all **blind tip reconstruction**, which has no
maintained Python 3 implementation.

TopoStats already made exactly this migration and did not go back.

### The Python 2.7 bridge

- Subprocess: `C:\Python27\python.exe script.py` with `PATH`/`PYTHONPATH`
  pointed at Gwyddion's `bin` and `share/gwyddion/pygwy`.
  **No `gwyddion.exe`, no CLI flags** — see [ECOSYSTEM.md §1.1](research/ECOSYSTEM.md).
  Already working: [`tools/run_py27.ps1`](../tools/run_py27.ps1).
- Wire format: `.gwy` via `gwyfile` (readable and writable from Python 3), or
  `.gsf` via `gsffile` for a lighter raw-float channel.
- Parameters in, results out: JSON on stdout.
- ⚠️ **Soak-test repeated subprocess spawning before committing.** GTK/GObject
  teardown in a repeatedly-spawned Python 2.7 process is a plausible source of
  leaks or hangs at scale; only single short-lived runs have been verified.

---

## Pipeline order

The established order is kept, with one addition the literature strongly
supports — **segmentation before flattening**:

```
raw height map
  → triage           (Ssk/Sku/Sz outliers; is this image worth processing at all?)
  → detect + segment (artifact mask; certainty map as a diagnostic)
  → flatten          (mask-aware -- fit on unmasked pixels only)
  → row / scar / step corrections
  → FFT denoise      (only after the real-vs-noise test passes)
  → baseline
  → score            (PSD bands, Str, Sdq, bias-corrected Sq)
  → export + log
```

**Flatten still precedes denoise.** What changes is that a mask is computed
first, so flattening is not biased by protruding objects — the mask-aware
"Smart Flatten" result reports a 2.7× reduction in line-wise residuals versus
conventional global polynomial fitting.

Tip deconvolution sits awkwardly in this order: it must run on *denoised* data,
but before any claim about lateral dimensions. Proposal: **report the certainty
map early as a diagnostic; run actual deconvolution late, as an optional,
explicitly-flagged step.**

---

## Multi-level masking

The original goal — mask an object, invert the mask, process background and
object separately, recombine — maps onto functions already present
([PYGWY_API.md](pygwy_api/PYGWY_API.md)):

| Need | Gwyddion function |
|---|---|
| Flatten with protruding features excluded | **`flatten_base`** |
| Mask outliers (>3σ) | `outliers` |
| Mask disconnected data | `mark_disconn` |
| Invert a mask | `mask_invert` |
| Combine masks | `mark_with` |
| Morphological ops on a mask | `mask_morph`, `mask_thin`, `mask_edt` |
| Fill under mask | `laplace` (Laplace), `fraccor` (fractal), `zeromasked` |
| Robust levelling | `trimmed_mean` |

`flatten_base` — "Flatten base of surface with positive features" — is close to
the exact use case, and the old pipeline never used it.

Prior work to reuse rather than restart:
`OLD scripts\batch_smart_process_iterative_masked.py` in the old project already
prototypes height-mask building, foreground/background blending, bounded
iteration (`MAX_ITERS=12`, early stop at 0.97) and reference scoring. It shares
the old FFT bug and only explores 12 of 32 grid combinations, so treat it as a
design reference, not a mergeable branch.

---

## Iterative loop

Bounded, as required — never an uncontrolled loop. Stop on any of: good match,
no improvement, or max iterations.

What changes versus the original plan is **the objective function**. See
[QUALITY_METRICS.md §6](research/QUALITY_METRICS.md). In short: score
artifact-band PSD power down, penalise out-of-band PSD change, reward Str toward
isotropy, penalise Sdq/Sdr collapse, report bias-corrected Sq but never minimise
it, and hard-stop at the instrument noise floor.

Training and validation pairs can be generated in-process: Gwyddion's
`lno_synth` **generates line noise including steps, scars, ridges, tilt and
hum**, and `lat_synth`/`pat_synth` generate genuine periodic structure — exactly
the negative control needed for the real-vs-noise discriminator.

---

## Safety rules

Taken from the AILA/AFMBench findings and the correctability analysis in the
[taxonomy](research/ARTIFACT_TAXONOMY.md).

1. **Refusal is a first-class output.** For not-tracking, charging, double tip,
   moiré and confirmed-real periodic structure, the correct action is to say so
   and stop. An app that confidently "fixes" these is worse than one that
   declines.
2. **Deterministic mediation between the LLM and the data.** The model selects
   from a bounded, validated operation set; a non-LLM layer checks parameters
   against physical limits before anything touches pixels.
3. **Never overwrite source data.** Every correction is a new version, with a
   full undo stack and a before/after preview.
4. **Never notch-filter a Fourier peak that passes the reciprocal-lattice
   test** without explicit user confirmation.
5. **Log every decision** with the parameters used and the metrics before and
   after, so a result can always be explained after the fact.
6. **Pin and regression-test prompts** — prompt fragility is documented and
   serious.

---

## Open questions

- Do the `.tiff` inputs carry calibrated height data, or are they rendered
  pictures? Treat `.ibw` as source of truth until checked.
- Are trace *and* retrace channels available in the `.ibw` files? If so, that is
  the highest-value under-exploited signal available — it underpins the best
  published learned corrector and gives a reference image for SSIM without
  ground truth.
- Does repeated PyGwy subprocess spawning stay stable over hundreds of calls?
- Does Gwyddion 3's GObject-Introspection expose the *process-function registry*
  (not just the libraries), and will anyone produce Windows builds?
