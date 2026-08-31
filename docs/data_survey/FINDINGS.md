# What the real data actually contains

Read from the 14 raw files in `C:\AFM_Automation\input` and
`C:\AFM_Automation\OLD input IMAGES`, through Gwyddion's own importers.
Raw output: [CHANNEL_SURVEY.md](CHANNEL_SURVEY.md), machine-readable in
`channel_survey.json`. Regenerate with:

```
tools\run_py27.ps1 tools\survey_channels.py <folder> [<folder> ...]
```

All 14 files read successfully — 8 Asylum `.ibw`, 6 `.tiff`.

---

## 1. There are no trace/retrace pairs. ❌

**Every `.ibw` file contains only `HeightRetrace`.** Not one file has both a
forward and a backward height channel.

| File | Height channels present |
|---|---|
| Calibration grating.ibw | `HeightRetrace`, `ZSensorRetrace` |
| Flakes1.ibw | `HeightRetrace` |
| Nanoparticles 3 Dense film.ibw | `HeightRetrace` |
| Noisy HOPG 1.ibw | `HeightRetrace`, `ZSensorRetrace` |
| Noisy HOPG 2.ibw | `HeightRetrace` |
| Single object high z step 1/2/3.ibw | `HeightRetrace` |
| Smooth polynomial surface - polymer.ibw | `HeightRetrace` |

The only trace/retrace pair anywhere is in
`Single object high z step 2.ibw` — but it is `LateralTrace` / `LateralRetrace`
(friction), **not height**.

### Why this matters

Trace/retrace was the highest-value detector available. A single pair
simultaneously diagnoses:

- **not tracking / parachuting** — asymmetric divergence between directions
- **hysteresis** — a position-dependent lateral offset between them
- **time-locked noise** (hum, vibration) — mirrored or shifted between them
- **real vs artifact features** — real features are direction-invariant
- **debris events** — present in one direction only

and it supplies a **reference image for scoring without ground truth**
(`SSIM(processed_trace, processed_retrace)` should rise under a good
correction). It also underpins the best published learned corrector
(Kocur et al.'s ResU-Net).

### Recommendation — an acquisition change, not a code change

**Configure the Asylum software to save both scan directions for the height
channel from now on.** This costs nothing at acquisition time (both directions
are already measured; only the retrace is being written out) and unlocks an
entire family of detectors that no amount of post-processing can substitute for.

Until then, the app must work single-direction, and several detectors in
[ARTIFACT_TAXONOMY.md](../research/ARTIFACT_TAXONOMY.md) — notably §6.1
not-tracking and §7.2 hysteresis — degrade from "measurable" to "inferred".

---

## 2. The TIFF files *are* real calibrated data. ✅

This resolves an open question from [ARCHITECTURE.md](../ARCHITECTURE.md) —
and the cautious assumption was **wrong**, in a good way.

| | |
|---|---|
| Channel | `Topography` |
| Size | 512×512 px |
| Physical extent | 5e-06 to 1e-05 m, correctly scaled |
| z unit | **`m`** — genuine metres, not greyscale |
| z range | 1.9e-07 to 1.4e-06 m |

They also carry acquisition metadata (`Scan rate`, `Set point`,
`Z servo gain`, `Line direction`). These are instrument exports with physical
calibration intact — **not rendered pictures** — so they are usable for
metrology and as training data.

Note they are a different vendor's export from the `.ibw` files (the metadata
key style and the `Topography` channel name differ from Asylum's), so the app
should not assume one metadata schema.

---

## 3. The metadata needed for hum prediction is present. ✅

This is the enabling finding for the hardest problem in the taxonomy
(§5.7, telling real periodic structure from periodic noise).

The strongest discriminator is **predict-from-metadata**: mains hum lands at a
frequency computable from the line rate and pixel count, so a spectral peak at a
*predicted instrument frequency* is noise, while one elsewhere gets the benefit
of the doubt. That requires acquisition parameters — and the `.ibw` files carry
them in abundance:

| Key | Example | Use |
|---|---|---|
| `ScanRate` | 0.78125 | **Line rate (Hz) — maps temporal frequency to spatial frequency** |
| `ScanPoints` / `ScanLines` | 256 / 256 | Pixels per line |
| `ScanSize` / `FastScanSize` / `SlowScanSize` | 5e-05 | Physical extent (m) |
| `ScanAngle` | **35** | Scan rotation — real structure rotates with the sample, artifacts do not |
| `Sample Rate` | 500 | Data acquisition rate |
| `Scan Time` | 00:05:28 | Total frame time |
| `IntegralGain` / `ProportionalGain` | 29.292 / 0 | **Feedback gains — ringing and overshoot scale with these** |
| `Setpoint`, `FreeAirAmplitude` | 0.0008, 0.95991 | **Their ratio predicts parachuting risk** |
| `DriveFrequency` | 285882.3 | Cantilever drive |
| `Date`, `Time` | 2023-09-18, 4:08:04 PM | Provenance |

Roughly 190 metadata keys per file are available; the survey tool filters to the
relevant ones.

Two of these deserve emphasis because they turn *acquisition-side* artifacts
into *predictable* ones:

- **`Setpoint` / `FreeAirAmplitude`** — the literature states the closer the
  setpoint is to the free amplitude, the more likely parachuting. That is a
  computable risk score, available before looking at a single pixel.
- **`ScanAngle` = 35°** is non-zero on the calibration grating. Any stripe
  pattern aligned with the *scan* frame rather than the *sample* frame is
  instrumental — and with a known scan angle, those two frames are
  distinguishable in a single image.

---

## 4. Consequences for the plan

| Finding | Effect |
|---|---|
| No height trace/retrace | Several detectors weaken; **ask for both directions at acquisition** |
| TIFFs are calibrated | 6 more usable images than assumed; the Python 3 reader must handle both vendors |
| Rich metadata present | The metadata-prediction discriminator for hum vs real structure **is buildable** |
| 14 real images total | Far too few to train on — hence the synthetic generator, [`tools/make_dataset.py`](../../tools/make_dataset.py) |
