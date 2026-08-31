# Quality metrics — how to score a correction without fooling yourself

The goal is **not** a smoother image. It is removing acquisition artifacts while
preserving real surface morphology. Those two objectives point in opposite
directions, and the naive metric (RMS roughness) points the wrong way.

Sources in [SOURCES.md](SOURCES.md).

---

## 1. The most important finding in the whole survey

**Nečas, Klapetek et al., "How levelling and scan line corrections ruin
roughness measurement and how to prevent it", Sci. Rep. 10, 15294 (2020).**

Every correction step **systematically biases Sq downward**, and the bias is
*quantifiable in closed form*.

- Framework: `E[σ̂²] = σ²(1 − β)`, with β the relative bias depending on
  **α = T/L** (correlation length ÷ scan length) and the dimensionality D of the
  levelling (D=1 for per-row, D=2 for whole-image).
- **1D (row-wise) levelling — bias ∝ α**, i.e. *linear* in T/L.
- **2D (whole-image) levelling — bias ∝ α²**, i.e. *much smaller*.

Reported magnitudes:

| Correction | Condition | Sq underestimation |
|---|---|---|
| 1D tilt removal | L/T ≈ 45 | **~8%** |
| 1D bow (degree 2) | L/T = 20 | **~25%** |
| 3rd-order polynomial | L/T = 15 | **~40%** |

**Rule of thumb, directly implementable:**

```
relative bias  ≈  (T / L) × (number of fitting parameters)
```

Worked example from the paper: a 10×10 μm scan, 2nd-order polynomial **row**
levelling, correlation length T = 0.4 μm → (0.4/10) × 3 = 0.12 →
**~12% underestimation**.

Correction: `σ²_corrected = σ²_measured / (1 − β)`.

Context: they analysed **1929 images from 300 papers** (2017–2018), median
L/T ≈ 43, and found the bias is *almost never* taken into account.

### Three consequences for this project

1. **Row-wise corrections are ~1/α times more damaging than image-wise ones.**
   Prefer 2D polynomial background over per-row levelling whenever the artifact
   permits, and **record which was used**.
2. The **autocorrelation length T** must be a first-class computed quantity,
   because it converts a correction choice into a *predicted* Sq bias.
3. **A naive "minimise Sq" optimiser will drive itself to maximum destruction.**
   Sq alone is an actively wrong objective function.

> This directly invalidates the approach used in the older `AFM_Automation`
> pipeline, which logged `rms_reduction` as a quality signal and trained on it.
> A larger RMS reduction was being treated as a better result; the physics says
> it is often just more damage.

---

## 2. Human-variability baseline

**Nečas & Klapetek, "Study of user influence in routine SPM data processing",
Meas. Sci. Technol. 28, 034014 (2017).**

Real humans processing *identical* SPM data with *identical* software produce
statistically dispersed answers — across atomic step height, rough-surface
roughness, and artificial smooth step height.

**This is the benchmark to aim at.** If the app is more *reproducible* than the
human distribution, that is a defensible and publishable claim — and a far
easier one to support than "more accurate".

---

## 3. ISO 25178 areal parameters, sorted by role

| Role | Parameters | Why |
|---|---|---|
| **Primary magnitude** | Sa, Sq | Standard — but scale-dependent and levelling-biased (§1) |
| **Anomaly flags** | **Ssk, Sku, Sz, Sp, Sv** | Extreme values flag tip scarring, loss of contact, contaminated tip, contamination particles |
| **Anisotropy** | **Str** (texture aspect ratio), **Sal** (autocorrelation length) | **Str near 0 = strongly directional** — exactly the signature of stripe artifacts |
| **Feature preservation** | **Sdr** (developed interfacial area), **Sdq** (RMS gradient) | Both collapse under over-smoothing |

Two of these deserve emphasis:

- **Str is an excellent, standards-backed objective for the iterative loop.**
  A correction that raises Str toward isotropy is removing directional noise;
  one that lowers it is imposing directionality.
- **A large drop in Sdq with only a small drop in Sq means you destroyed
  morphology, not noise.** That ratio is a cheap over-smoothing alarm.

An empirical result worth implementing on day one: in a high-speed-AFM quality
control study of >200 images, **extreme values of skewness, kurtosis and maximum
roughness reliably flagged anomalous frames** (tip scarring, loss of contact,
contaminated tip, contamination particles). A statistical filter on Ssk/Sku/Sz
is a cheap, physically-motivated first-pass triage detector.

### ISO 25178-3 filtering vocabulary

Worth adopting as internal language because it matches the pipeline stages
exactly:

| Term | Meaning | Pipeline stage |
|---|---|---|
| **F-operation** | Form removal | flatten / plane / bow |
| **L-filter** | Removes long-scale (waviness) | baseline correction |
| **S-filter** | Removes short-scale (noise) | FFT denoise |
| **Nesting index** | The cutoff wavelength | the tunable parameter |

Guidance: the L-filter nesting index should be **~5× the coarsest feature you
want to keep**.

---

## 4. PSD — recommended as the primary scorer

For an iterative parameter-scoring loop, PSD-based metrics are the most robust
and physically meaningful option, for four reasons:

1. **Band-selective.** Score the change in *only* the frequency bands you
   intended to touch, and **penalise change elsewhere**. A destriping step
   should reduce power on the k_x=0 axis and leave the rest alone — that is
   directly measurable.
2. **Scale-explicit.** Sidesteps the RMS scale-dependence problem: the PSD
   describes roughness *at each length scale*, whereas "surfaces with very
   different morphology may have the same RMS".
3. **Model-fittable.** Fractal or k-correlation (ABC) fits give correlation
   length, fractal dimension and Hurst exponent. **Those should be invariant
   under a correct correction** — invariance of the Hurst exponent is a strong
   feature-preservation test.
4. **Noise-floor referenced.** Compare against the instrument's measured noise
   floor (0.3–1 Å RMS typical) and **stop filtering when you reach it** — a
   principled stopping criterion instead of an arbitrary one.

Detector constructions from the PSD, mapped to the taxonomy:

| PSD feature | Artifact |
|---|---|
| Excess power at lowest k | Bow |
| Excess power on the k_x = 0 axis | Row offsets |
| High-k shelf on fast axis only | Line noise |
| Isolated peak above local spectral median | Periodic noise |
| Premature high-k roll-off | Blunt tip, or over-smoothing |
| Flattening at 0.3–1 Å | Instrument noise floor reached |

Gwyddion computes 1D/2D PSDF, ACF and HHCF natively.

---

## 5. SSIM / PSNR — usable, with a caveat

SSIM is the de facto metric in AFM destriping evaluation (the 16-method
benchmark below used SSIM primary, PSNR auxiliary). But both are
**full-reference**, and in real use there is no ground truth.

Two legitimate ways to use them anyway:

1. **Synthetic ground truth.** Generate degraded/clean pairs with Gwyddion's own
   `lno_synth` (line noise: steps, scars, ridges, tilt, hum) and `noise_synth`
   generators, tune the parameter policy against true SSIM offline, then deploy
   the learned policy. **This is available in-process via PyGwy** — see §7.
2. **Reference-swap.** Use **retrace as the reference for trace**. Not ground
   truth, but an independent measurement of the same surface with *opposite*
   time-locked artifacts. `SSIM(processed_trace, processed_retrace)` should
   *increase* under a good correction.

---

## 6. A concrete proposal for the iterative scorer

Nothing published assembles this; it follows from the sources above.

**Objective = weighted sum of:**

| Term | Direction |
|---|---|
| Artifact-band PSD power (k_x=0 axis, detected periodic peaks, stripe direction) | **minimise** |
| Out-of-band PSD change (L2 on log-PSD outside targeted bands) | **minimise** — the morphology-preservation term |
| Str movement toward isotropy | **reward**, capped at the value expected for the sample class |
| Sdq / Sdr retention | **penalise large drops** (over-smoothing alarm) |
| Hurst exponent / fractal dimension change | **penalise** |
| Bias-corrected Sq (§1) | **report, never minimise** |
| Trace/retrace SSIM after processing | **maximise**, when both channels exist |
| Distance to instrument noise floor | **hard stop** — do not filter below it |

**Hard constraints — refuse rather than score:**

- Never remove a Fourier peak that passes the reciprocal-lattice consistency
  test ([taxonomy §5.7](ARTIFACT_TAXONOMY.md#57-real-periodic-structure-vs-periodic-noise--the-hard-problem))
  without user confirmation.
- Never apply a correction whose *predicted* Sq bias exceeds a user-set budget.
- Never claim a lateral dimension for regions flagged by the certainty map.

---

## 7. Training and validation data — Gwyddion generates it for you

Confirmed present in this install (see [PYGWY_API.md](../pygwy_api/PYGWY_API.md)):

| Function | Menu | Use |
|---|---|---|
| `lno_synth` | /Synthetic/Noise/Line Noise | **Generates line noise: steps, scars, ridges, tilt, hum** |
| `noise_synth` | /Synthetic/Noise/Noise | Uncorrelated noise |
| `fft_synth` | /Synthetic/Noise/Spectral | Spectral synthesis |
| `lat_synth` | /Synthetic/Lattice | Lattice-based surface — for the real-periodic-structure test |
| `pat_synth` | /Synthetic/Pattern | Patterned surface |
| `obj_synth`, `particle_synth`, `fibre_synth`, `phase_synth`, … | /Synthetic/… | ~24 generators total |

This solves the AFM data-scarcity problem the ML literature complains about:
**clean/degraded pairs with known ground truth can be produced in-process, by
the same library that will do the correcting.**

The external complement is Kocur et al.'s public training-set generator plus an
evaluation dataset of 82 real AFM scans across 10 physical samples.

---

## 8. Benchmark result worth knowing before writing any destriping code

**Li et al., "Stripe noise removal in conductive atomic force microscopy",
Sci. Rep. 14 (2024)** compared **16 methods** on simulated data with known
ground truth: 9 Gwyddion algorithms (Median, Mode, Trimmed Mean, Median
Difference, Matching, Trimmed Mean Difference, Facet Level Tilt, Polynomial
Fitting, Remove Scar) plus VSNR, DeStripe2, the deep-learning SNRWDNN, and three
optimisation methods (LRR, GSR, UTV).

**Result: LRR (low-rank recovery) wins — 90.43% mean SSIM**, "removing gradient
stripe noise while preserving the edges and important features". Robust across
noise intensity, **one fixed parameter, no GPU**. Polynomial fitting was second
and became competitive at higher noise levels. The deep-learning method did not
win.

Their own framing: robust destriping methods proven in other fields "are not yet
commonly used in AFM image processing".

**Takeaway: LRR is a strong, cheap, one-parameter default that beat every
Gwyddion row-levelling method on their benchmark — and it can run in Python 3
alongside PyGwy.**
