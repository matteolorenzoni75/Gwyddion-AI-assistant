---
title: Lateral distances need two corrections, not one
tags: [calibration, piezo, drift, distortion, tip, gwyddion, dvd]
verified: 2026-09-03
confidence: measured
---

Every lateral size this software reports is wrong twice over until corrected,
and the two errors are independent:

1. **The tip widens what it touches** — [[the-tip-is-in-every-measurement]].
2. **The scanner mismeasures where it is** — piezo non-linearity, creep and
   drift. The user's instruction: *"le distorsioni da drift o da non linearità
   piezo vanno sempre controllate e se possibile corrette, gwyddion ha varie
   funzioni per questo."*

A height is largely free of both. A width or a spacing is not.

## Measured, on a sample with a certified answer

The training set holds four scans of a DVD, whose track pitch is **740 nm** by
specification. Two scanner states, and they do not agree with each other:

| scan | pitch found | vs certified |
| --- | --- | --- |
| `DVD 260701003001` / `002` | 744 nm | **−0.6%** |
| `DVD240122003005` / `006` | 830–857 nm | **+12 to +16%** |

Same sample. The difference between the two is the instrument, and it is large:
a 15% error on every distance in that scan. This was first read as a wrong
label — the user corrected it, and was right.

## Scale error or non-linearity?

Different faults need different corrections, so the distinction matters. A
uniform scale error is one number; non-linearity compresses one edge of the
frame and stretches the other, and needs a real transform.

Measuring the spacing peak by peak across the frame of `DVD240122003005/006`
gives a pitch uniform to about 2–3% with a mean 15% too high — which **looks
like a scale error rather than non-linearity**. Stated with its limit: there
are only eight or nine tracks in the frame, so the trend across it is poorly
determined, and the two scans of the pair disagree on the trend (+8.4% against
+2.5%). Not enough to exclude non-linearity, enough to say the bulk of the
error is uniform.

The same measurement on `DVD 260701003001/002` is worthless — six peaks with
40% scatter — so nothing is claimed from it beyond the FFT pitch.

## What Gwyddion offers

Under *Data Process → Distortion*:

- **Affine correction** — the right tool for exactly this case: give it the
  expected lattice and it computes the affine transform that maps measured to
  true, correcting scale, shear and rotation together.
- **Drift compensation** — estimates slow lateral drift between scan lines and
  removes it.
- **Polynomial distortion** — for the non-linear case, when an affine map is
  not enough.

## The consequence for this project

**A DVD in the sample set is a lateral standard, not just a test image.** Any
scan of it dates and quantifies the state of the scanner, and that factor
applies to every other scan taken in the same session.

So the rule is: never present a lateral distance as the sample's without saying
what has been corrected. Height, yes. Width and spacing, only with the tip and
the scanner accounted for — or with the caveat attached.
