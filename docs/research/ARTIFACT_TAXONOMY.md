# AFM height-map artifact taxonomy

This is the **recognition target list** for the app: the things the system must
learn to name before it is allowed to correct anything. Scope is the height
channel only.

Each entry gives the visual/data signature, the physical cause, how it can be
detected quantitatively, and how (or whether) it can be corrected. The last
column matters most: **several of these are not correctable in post-processing
at all**, and the correct output for those is a refusal plus a rescan
recommendation.

Sources are listed in [SOURCES.md](SOURCES.md). The canonical framing — five
artifact sources: *tip, scanner, vibration, feedback circuit, and the image
processing software itself* — is from Ricci & Braga (2004).

That fifth category is not a joke, and it is the one this project is most at
risk of creating. See [§10](#10-processing-induced-artifacts).

---

## 1. Background / form artifacts

Removed first, before everything else.

### 1.1 Sample tilt
- **Signature.** Monotonic linear ramp across the field. Height histogram
  broadened into a plateau rather than peaked. Fitted plane has non-zero x/y
  slope dominating the height range.
- **Cause.** Sample not mounted normal to the z-axis; intrinsic scan-plane tilt.
- **Detection.** Least-squares plane fit; report residual Sq vs raw Sq and the
  tilt angle. Robust variant: **facet-level**, which histograms local surface
  normals — a sharply peaked normal distribution pointing off-vertical *is* the
  tilt signature. Unsuitable for random/rough surfaces.
- **Correction.** Gwyddion `level` (Plane Level), `level_rotate` (rotate rather
  than subtract — preserves true facet angles), `facet-level`.
  **`level_rotate` vs `level` is a physical choice, not cosmetic:** if the user
  cares about facet angles, subtracting a plane distorts them.

### 1.2 Bow / scanner curvature
- **Signature.** Symmetric dome or dish, strongest along the fast axis.
  Parabolic (2nd order) in tube scanners; S-shaped 3rd-order components appear
  at large scan sizes.
- **Cause.** Piezo tube scanners move the tip on a **parabolic arc**, not a
  plane. Open-loop tube scanners are worst; flexure/closed-loop much less so.
- **Detection.** Fit polynomials of increasing degree; the degree at which the
  residual-variance improvement saturates is the bow order. Second, more
  physical test: **bow is scan-size dependent and sample-independent**, so its
  curvature coefficient should scale with scan range.
- **Correction.** `polylevel` (polynomial background), `arc_revolve` /
  `sphere_revolve` (rolling-ball envelope — better when prominent features must
  not be fitted through), `flatten_base` (facet + polynomial levelling **with
  automatic masking of prominent features**).
- **Warning.** Polynomial background removal is the single largest documented
  source of roughness bias. See [QUALITY_METRICS.md](QUALITY_METRICS.md) §1.
  The order is not a free parameter.

### 1.3 Thermal drift
Two distinct manifestations that must be separated:
- **Lateral (xy) drift** → shear/skew: circles become ellipses, square lattices
  become oblique. The same feature appears displaced between up-scan and
  down-scan frames.
- **Vertical (z) drift** → slow monotonic ramp along the **slow** axis. This
  masquerades as tilt but is not: it is time-dependent, not space-dependent, so
  no physical plane removes it correctly. The literature calls the result an
  "illusory slope".
- **Detection.** Three published families, all in the open-source *unDrift*
  tool: (i) lattice vectors from FFT/autocorrelation of two consecutive frames
  with **opposing** scan directions; (ii) **cross-correlation** between
  consecutive same-direction frames; (iii) manual feature tracking. Reported
  accuracy on calcite: ±25 pm, ±2°.
- **Correction.** Affine/shear resampling. Gwyddion has a `drift` module for the
  fast axis. For the joint problem, DHCT fits drift + hysteresis + creep
  together against a known lattice.
- **Honest limitation.** Every accurate method needs periodicity, stationary
  features, or a second frame. **On a single unstructured height map, drift is
  not separable from real tilt.** The app must say so rather than silently
  "correcting" it.

---

## 2. Line / row artifacts (the fast-axis family)

Where Gwyddion is richest and where most automatic gains will come from.

### 2.1 Row-to-row height offsets ("striping", "banding")
- **Signature.** Horizontal bands of constant offset; each *whole row* displaced
  in z. In the 2D FFT this puts power on the **vertical frequency axis
  (k_x = 0)** — a broadband vertical line through the origin. The row-median
  difference sequence is high-variance and uncorrelated row to row.
- **Cause.** z-drift within a line-time, feedback baseline wander, 1/f
  electronic noise, detector thermal drift, gain glitch.
- **Detection.** Median (or trimmed mean) of each row, plus the **median of
  row-to-row differences**. A near-white offset sequence distinguishes artifact
  from genuine long-wavelength waviness. Also: power concentrated on the k_x=0
  axis of the 2D PSD relative to an isotropic expectation.
- **Correction.** `align_rows`, and **the estimator choice matters enormously**:

  | Method | Behaviour |
  |---|---|
  | Median | Robust, but destroys real long-wavelength structure |
  | Modus | Better when a flat substrate dominates |
  | Polynomial (deg 0/1/2) | 0 = offsets, 1 = per-row slope, 2 = per-row bow |
  | **Median of Differences** | **Documented as better preserving large features — usually the right default** |
  | Trimmed Mean (of Differences) | Continuous mean↔median interpolation via a trimming fraction — a *tunable knob* for an optimiser |
  | Matching | Experimental; weights flat areas over steep slopes |
  | Facet-level Tilt | Per-row tilt only |

  All support **masking** to exclude features from the estimator. Use it.

### 2.2 Mid-row jumps / step discontinuities
- **Signature.** A row correct up to some column, then jumping to a different
  baseline. Ragged vertical "tear".
- **Cause.** Feedback losing and regaining lock; a tip event mid-line.
- **Detection.** Within-row change-point detection. Gwyddion's block correction
  uses a threshold expressed as a **multiple of image RMS** and **requires
  knowing the slow-scan direction** (top-to-bottom vs bottom-to-top) — a real
  and often-missed input.
- **Correction.** `line_correct_step`, `block_correct_step`.

### 2.3 Line noise (high-frequency, per-row)
- **Signature.** Grainy fast-axis noise on every row; broadband high-k_x power.
  Typical instrumental noise is **0.3–1 Å RMS** — a useful *physical floor*.
- **Detection.** Compare the **1D PSD along the fast axis** to the slow axis: a
  white high-frequency shelf present only along fast-x is instrumental.
- **Correction.** 1D FFT low-pass, conservative Gaussian. Gwyddion's XY
  denoising uses **two perpendicular scans** — principled, because the artifact
  is scan-direction-locked and the sample is not.

### 2.4 Inverted rows
`line_correct_inverted` marks scan lines whose features are vertically inverted.
Rare on height, cheap to include as a detector.

---

## 3. Point defects

### 3.1 Scars / strokes
- **Signature.** Short, thin, **fast-axis-parallel** streaks, typically 1–3 px
  wide and many px long, positive or negative.
- **Cause.** Gwyddion's own definition: corruption "from local fault of the
  closed loop". Also tip momentarily grabbing/releasing debris.
- **Detection.** `scars_mark` is the best-specified quantitative detector in the
  Gwyddion corpus: **maximum width** (px), **minimum length** (px), **hard
  threshold** (height difference from the rows above *and* below, relative to
  image RMS), **soft threshold**, **defect type** (positive/negative/both).
  The structural insight worth reusing: a scar is defined by being anomalous
  **with respect to the rows above and below** — anisotropic in exactly the way
  real morphology is not.
- **Correction.** `scars_remove` (interpolates from neighbouring lines).

### 3.2 Spikes / dropouts
- **Signature.** Isolated pixels many σ from their local neighbourhood.
- **Cause.** Electrical spikes, ADC glitches, momentary loss of contact, dust.
- **Detection.** Sliding-window deviation criterion; iterative n-σ clipping
  (3σ common). Gwyddion has `outliers` (Mask of Outliers, >3σ from mean) and
  `mark_disconn` (Mask of Disconnected).
- **Correction.** Mask and interpolate — `laplace` (Laplace equation under mask)
  or `fraccor` (fractal interpolation). **Never global smoothing** to remove a
  handful of pixels; that is the classic case of destroying morphology.

---

## 4. Tip artifacts

### 4.1 Tip convolution / dilation
- **Signature.** **Lateral dimensions overestimated, heights approximately
  correct.** All features acquire the same apparent sidewall shape — the tip's.
  When a feature is sharper than the tip, the image shows the *tip*.
  Repeated identical triangular/pyramidal shapes are the tell.
- **Cause.** The image is the **morphological dilation** of the surface by the
  reflected tip. Worst when feature size ≈ tip radius (1–10 nm).
- **Detection.** **Certainty map** (Villarrubia): marks where the surface was
  touched at a single point versus multiple points. Multi-point regions carry
  **irreversible** information loss. This is exactly the right thing to report:
  *"X% of this image is not recoverable by deconvolution."*
- **Correction.** Blind tip reconstruction (Villarrubia 1997). Gwyddion
  implements the whole family: tip modelling, blind estimation (partial = fast,
  full = slow), dilation, surface reconstruction (erosion), certainty map, and a
  **stripe-wise mode that tracks how tip shape evolves down the scan — a direct
  tip-wear detector**.
- **Known failure mode.** BTR is provably an *upper bound* on sharpness and is
  **highly noise-sensitive** — noise spikes carve the tip too sharp. It must run
  on denoised data.

### 4.2 Double / multiple tip
- **Signature.** Every feature appears **twice**, with a **fixed displacement
  vector** across the whole image, because the geometry of the two apexes is
  fixed. Reads as a ghost or directional shadow.
- **Detection.** The fixed offset is the handle: **autocorrelation** shows a
  strong secondary peak at the tip-separation vector, not attributable to sample
  periodicity. CNN classification of sharp vs double tip is reported at 97%
  single-image accuracy, >99% with majority voting.
- **Correction.** **None. Change the tip and rescan.** Deconvolution of a double
  tip is ill-conditioned. Classify and report.

### 4.3 Blunt tip
Loss of lateral resolution; small features rendered as larger rounded ones.
Detect by comparing BTR-estimated apex radius across a scan series
(stripe-wise blind estimation is designed for this), or by high-k PSD roll-off
moving to lower k over successive scans. **Correction: replace tip.**

### 4.4 Tip contamination
- **Signature.** Streaking; strange repeated shapes; **sudden change in apparent
  morphology partway down the image** (a pickup event).
- **Detection.** The best signal is **change along the slow axis**: row-wise
  statistics (row Sq, Sa, skew) that step-change at a given row. ML classifiers
  report **93% recall** for this class.
- **Correction.** **Not correctable in post.** Detect, report, rescan.

---

## 5. Periodic / oscillatory noise

This is where the "arbitrary orientation" requirement bites hardest.

### 5.1 Mains hum (50/60 Hz and harmonics)
- **Signature.** Fine regular quasi-sinusoidal ripple. **Orientation and
  apparent wavelength depend on the scan rate and line rate**, because the noise
  is periodic in *time* and the raster maps time to space. Not necessarily
  axis-aligned. In Europe expect a 50 Hz fundamental with strong 100 Hz content.
- **Detection.** Sharp, isolated, conjugate-symmetric peak pairs in the 2D FFT.
  **Crucially you can predict where they should be:** given line rate f_line and
  pixels-per-line N, a temporal frequency f maps to a known (k_x, k_y).
  **This is the single strongest discriminator between hum and sample
  structure** — and it uses acquisition metadata that no image-only published
  method exploits.
- **Correction.** Notch filtering: `fft_filter_1d`, `fft_filter_2d`. Windowing
  is mandatory to avoid spectral leakage.

### 5.2 Acoustic / mechanical vibration
Blurred images or saw-tooth patterns along feature edges, tied to building/HVAC
modes. Same FFT machinery; the distinguishing feature is that the frequency is
*not* a mains harmonic and is often non-stationary. Best fixed at acquisition.

### 5.3 Optical / laser interference
- **Signature.** An unusually crisp fingerprint: sinusoidal pattern with a
  **spatial period of 1.5–2.5 μm**, usually along the fast axis.
- **Detection.** A peak in that spatial-wavelength band that **does not scale
  with scan rate** (unlike hum) and is fixed to neither sample nor raster.
  Correlates with sample reflectivity.
- **Correction.** Re-align laser at acquisition; notch filter in post.

### 5.4 Piezo resonance / ringing
- **Signature.** Rings around raised features; features looking "surrounded by
  water". **Feature-localised, not field-uniform.**
- **Detection.** Detect in real space, not spectrally: oscillatory overshoot
  immediately after step edges, decaying with distance. Ringing metric =
  amplitude of the first over/undershoot lobe relative to step height.
- **Correction.** Acquisition-side. **Not safely removable in post.**
- **Useful cue:** *where* the oscillation lives discriminates cause —
  field-wide ⇒ gains too high; feature-localised ⇒ resonance.

### 5.5 Moiré (raster × sample-lattice aliasing)
Long-wavelength beat pattern that is **not reproducible** and whose direction
depends on scan parameters — that non-reproducibility is the diagnostic. Change
scan angle or pixel density and a moiré pattern moves; real structure does not.
**Filtering cannot recover the true lattice from an aliased image.**

### 5.6 The arbitrary-orientation problem
Almost all AFM destriping in the wild assumes **axis-aligned** stripes. Oblique
stripe removal is solved in *remote sensing*, not in SPM.

Transferable approaches:
- **Oriented variation model** (Chen et al.) — explicitly targets "stripe noise
  with arbitrary orientations", **automatically detects the stripe direction**,
  then embeds that estimate into the regularisation.
- **Radon transform** — the natural orientation estimator, the generalisation of
  the Hough transform for line detection.
- **Cheaper equivalent:** oriented stripes produce power concentrated on a
  **line through the FFT origin perpendicular to the stripe direction**.
  Estimating stripe angle = estimating the dominant orientation of that ridge,
  via the structure tensor / second moment of the log power spectrum, or by
  maximising the angular integral of |F(k)| over θ. O(N log N), no Radon
  machinery needed.

  *Not found published for AFM.* Treat as an obvious-but-unpublished
  construction — and therefore as something to validate carefully, not assume.

### 5.7 Real periodic structure vs periodic noise — the hard problem
**No paper solves this properly for AFM.** The literature acknowledges the risk
and moves on. Proposed decision rule, assembled from adjacent work:

1. **Predict-from-metadata (strongest).** Hum lands at (k_x, k_y) computable
   from line rate, pixels/line and scan size; optical interference at
   1.5–2.5 μm. Anything at a *predicted instrument frequency* is noise.
2. **Scan-parameter invariance (the field's gold standard).** Rotate the scan
   angle and re-image: real structure rotates with the sample, instrumental
   patterns stay locked to the scan frame. The app can *request* this frame
   rather than guess.
3. **Harmonic structure.** A real lattice produces a **full reciprocal
   lattice** — multiple orders at integer combinations of two primitive vectors.
   Periodic noise typically gives one fundamental plus a few harmonics along a
   single direction. Fit two primitive reciprocal vectors and check residuals.
4. **Peak significance.** A true tone sits far above the *median* of its
   spectral neighbourhood (robust version of DeStripe's heterogeneity function,
   which combines the Laplacian of the log spectrum with intensity magnitude).
5. **Spatial extent.** Instrumental noise covers the **whole field including
   bare substrate**; sample periodicity is confined to where the sample is.
   A windowed FFT showing the peak in bare regions is strong evidence for noise.
6. **Trace/retrace consistency.** Real features appear identically in both;
   time-locked noise appears mirrored or shifted.

**Rule for the app: refuse to notch-filter any peak that passes the
reciprocal-lattice test (3) without explicit user confirmation.** This is
precisely the judgement call where an LLM with context ("the user told me this
is a calibration grating") earns its place.

---

## 6. Feedback-loop artifacts

### 6.1 Not tracking / parachuting
- **Signature.** **Tails on features** — the tip fails to follow the descending
  side, so features acquire an asymmetric trailing skirt in the fast-scan
  direction. Descending edges smeared, ascending edges sharp. **Asymmetry
  between the two scan directions is the fingerprint.**
- **Cause.** Gains too low, scan rate too high, or setpoint too close to the
  free amplitude.
- **Detection.** Trace/retrace divergence; directional edge asymmetry that flips
  sign in the retrace image. **This is the hardest class for ML — 60% recall
  reported.**
- **Correction.** **None. The data was never acquired.** The app must be able to
  say "unrecoverable, rescan". This is also the class where a wrong answer costs
  the user the most.

### 6.2 Overshoot / undershoot at step edges
Spike immediately after a step edge; **artificially increased step heights**.
Cause: gains too high. Detect by fitting the post-edge profile to a damped
oscillation; overshoot appears on the leading edge in trace and the opposite
edge in retrace. Contaminates step-height metrology directly — which is why
ISO 5436 evaluates averaged plateau regions excluding the edge zone.

### 6.3 Scan-speed artifacts
Misshapen features, smeared edges, worse tracking. Strength of all feedback
artifacts scales with (scan rate × feature slope).

---

## 7. Scanner nonlinearity

- **Creep.** Distortion concentrated at the **start** of a scan, decaying
  logarithmically. Features near the top stretched relative to the bottom.
  Detect: local period varies systematically down the slow axis on a known
  grating; compare first vs last rows' autocorrelation length.
- **Hysteresis.** Trace and retrace **laterally offset and differently scaled**.
  Detect by cross-correlating trace against retrace: a *position-dependent*
  shift (rather than a constant one) is hysteresis.
- **Cross-coupling (z↔xy).** Tube scanners couple lateral motion into z. Largely
  indistinguishable from bow in a single image — and it is the physical reason
  the polynomial background exists.

Correction for all three: closed-loop scanners, calibration-grating-derived
correction functions, or the joint DHCT fit. Gwyddion has `Global Distortions`
for applying general coordinate transforms.

---

## 8. Tip–sample interaction

- **Electrostatic charging.** The image "may not correspond to topography" at
  all. Large smooth feature-uncorrelated height variations, sensitive to scan
  speed and setpoint. **Height contrast that changes with setpoint is not
  topography.** Definitive resolution needs a KPFM/surface-potential channel —
  outside the height-only scope, which is an honest limitation to flag.
  Not post-processable.
- **Adhesion / soft samples.** Multiple probe–sample contact points; features
  smeared in the fast-scan direction. Detect via trace/retrace asymmetry and
  scan-speed dependence. Not post-processable.
- **Sample deformation under load.** Heights systematically **underestimated**
  for compliant features. Contrast changes with setpoint. Needs mechanical
  modelling.
- **Tip-induced sample damage.** Detect by comparing successive drift-corrected
  frames of the same area; a monotonic trend in Sq or feature count is the flag.

---

## 9. Step-height measurement artifacts

Measured step height depends on where you measure relative to the edge, and is
biased by feedback overshoot (§6.2), tip sidewall (§4.1) and residual bow (§1.2)
simultaneously.

**ISO 5436** defines the procedure: profile length ≥ 3× step width, and
h = (A + B)/2 − C where A, B, C are averages over the **middle third** of the
upper, upper and lower regions — edge zones deliberately excluded.

**Implication:** if the app is asked "what is the step height", it must report
which background correction was applied, because the answer depends on it.

---

## 10. Processing-induced artifacts

Ricci & Braga's fifth category. **These are artifacts this app can create.**

| Artifact | Signature | Cause |
|---|---|---|
| Line-levelling bands | Horizontal banding where a large feature crossed a row and biased that row's estimator | Median/mean row levelling applied **without masking features** |
| Dark/bright halo around features | Ring around tall objects | Polynomial background fitted *through* features instead of around them |
| Flattened-out real waviness | Long-wavelength morphology gone; Sq systematically low | Polynomial degree too high |
| FFT nodules / ringing | Ripple containing noise; ringing near edges | Sharp notch masks without apodisation (Gibbs) |
| Feature dimension change | Widths/heights altered | Aggressive smoothing before measurement |

The quantitative version of the damage is in
[QUALITY_METRICS.md](QUALITY_METRICS.md) §1: every levelling step biases Sq
downward by a *calculable* amount.

---

## Correctability summary

The single most important column for the app's behaviour.

| Class | Post-processable? |
|---|---|
| Tilt, bow, row offsets, scars, spikes | **Yes** — this is the bread and butter |
| Mains hum, optical interference, vibration | **Yes, with care** — must pass the real-vs-noise test first |
| Tip convolution | **Partially** — BTR, bounded by the certainty map |
| Drift, creep, hysteresis | **Only with periodicity, a reference, or a second frame** |
| Ringing at edges | **No** (safely) |
| Not tracking / parachuting | **No** — data never acquired |
| Double tip, blunt tip, contamination | **No** — change the tip |
| Charging, adhesion, deformation | **No** — acquisition-side |
| Moiré | **No** — re-acquire with different sampling |

**Design consequence: refusal must be a first-class output of this system.**
An app that confidently "fixes" a not-tracking image is worse than one that
declines and explains why.
