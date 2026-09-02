---
title: The sample library is the exam, not the training set
tags: [testing, reference, calibration, tip, periodicity, roughness]
verified: 2026-09-02
confidence: from-user-document
---

The user keeps a documented AFM sample library — twelve samples so far, each
with instrument, mode, probe, scan size and **the values they measured**. Read
from `SAMPLE CATALOG Layout2.docx` and recorded machine-readably in
`data/reference_samples.json`.

This is worth more than any quantity of unlabelled scans, because these numbers
are answers. Seven of them can be checked on the height channel alone:

| sample | quantity | value |
| --- | --- | --- |
| Mica, freshly cleaved | RMS | **36 pm** |
| ITO glass | Sq | **402 pm** |
| Anodic porous alumina | pore radius / pitch | **35 nm / 74 nm** |
| Gold electrodes | step height | **201 nm** |
| PS-PMMA, cylinders and lamellae | pitch | **36 nm** |
| Lambda DNA on mica | height / real width | **1.34 nm / ~10 nm** |
| DVD | track pitch | **740 nm** (their FFT: 733.5 nm) |

## Why each one earns its place

- **Mica at 36 pm is the floor.** If the pipeline cannot return 36 pm here, its
  levelling is adding roughness rather than removing it — which is precisely
  the Nečas bias, made checkable.
- **APA tests both broken measurements at once.** Its features go *downward*,
  so the object counter must stop looking only upward
  ([[what-the-survey-of-31-found-broken]]), and its 74 nm pitch is the
  periodicity answer at a scale where the two-pixel failure would show
  instantly.
- **PS-PMMA is periodic but not straight.** The fingerprint pattern meanders,
  so a method that only finds straight stripes will miss it while finding the
  grating in the pool. Two different tests of the same measurement.
- **The DVD is the periodicity exam.** A certified 740 nm, already reproduced
  to 0.9% by a plain FFT on the user's own machine. Our pool contains a DVD
  scan on which the current measurement returns 22 nm — the two-pixel limit.
  The gap between 733.5 and 22 is the whole bug, with a certified answer
  sitting next to it.
- **The DNA is the tip correction, worked by hand.** A filament 1.34 nm tall
  reads 40 nm wide; with a 10 nm tip its real width is about 10 nm.

## The catalog already contains the tip formula

One of its figures derives it: *apparent feature width ≈ 2x = 4·√(R_tip·R_feature)*.
The user applies it by hand to the DNA. So [[the-tip-is-in-every-measurement]]
is not a proposal — it is standard practice here that the software does not yet
do. TiO₂ nanorods 3–4 nm wide imaged with a ~25 nm tip make the point at its
sharpest: the apparent width is several times the real one, and reporting the
measured value as the object's size would be simply wrong.

## Two practical limits

**The catalog holds exported figures, not raw files.** Scale bars are burned
into the pictures; there are no units a program can read. Running these as
automatic tests needs the raw scans — expected in the 13 GB batch.

**Most entries were measured on other channels** — KPFM potential, Young
modulus, current, phase. Height only, as agreed for now, so those numbers are
recorded but not yet testable. They are not wasted: the sample identities and
morphologies transfer to the height channel unchanged.

## And it fills the gap at the small end

The library runs from 100 nm to 9 µm; the 31-scan pool runs from 4 to 45 µm.
Together they cover most of the 10 nm – 100 µm range the software is meant to
handle, which no single set did before.
