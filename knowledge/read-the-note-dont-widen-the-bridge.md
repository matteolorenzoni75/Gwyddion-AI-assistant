---
title: Read the note, don't widen the bridge
tags: [architecture, metadata, instrument, simplicity, dependencies]
verified: 2026-09-03
confidence: measured
---

The scan note — several hundred fields the instrument writes beside the pixels
— was the biggest single blocker on the list. Conversion to Gwyddion drops all
of it, and the obvious fix was to teach the Python 2.7 bridge to carry it
across, touching both sides of the two-runtime split.

**The simpler fix was to not use the bridge for this at all.** `igor2` reads
Igor Binary Waves in Python 3, so the note comes straight from the original
file that is still sitting next to the converted one. One small dependency,
one new module (`instrument.py`), no change to the Python 2.7 side.

The rule this illustrates, at the user's instruction — *"non voglio creare un
mostro di codice, evitiamo la proliferazione dell'albero quanto possibile e
prediligiamo la semplicità di architettura"*: before adding a step to an
existing chain, check whether the thing you need is available without the
chain.

## What the note turned out to hold

More than expected, and two findings changed the plan rather than confirming
it.

**Every Asylum file already carries four channels** — `HeightRetrace`,
`AmplitudeRetrace`, `PhaseRetrace`, and either `NapPotentialRetrace` or
`ZSensorRetrace`. The multichannel work for dynamic AFM that the user placed
in the future needs **no new reader**: the data has been in the files all
along. `ZSensorRetrace` is the measured z position, so comparing it against
Height is a direct reading of the scanner's own error.

**All of them ran `Closed Loop`.** So the 12–16% lateral discrepancy measured
on the DVDs cannot be blamed on open-loop piezo non-linearity in these scans —
and the DVDs are `.tiff` from a different microscope entirely. See
[[lateral-distances-need-two-corrections]]; the finding stands, the cause is
still open.

**The instrument records mid-scan interventions.** A field written as
`0.40064@Line: 229` says a setting was changed at that line. It is the only
record that the two halves of an image were not taken under the same
conditions, and it explains scans whose character changes half way down — one
of which had already been noticed by eye during the survey. Six of seventeen
files carry one. Two of those sit at line 509 of 512, which is the operator
adjusting something as the scan ended and leaves nothing behind, so only
changes in the body of the frame are reported.

## What was deliberately not adopted

Looked at, and turned down, each for a reason:

- **TopoStats** — a complete and competent AFM pipeline, which is exactly why
  not: adopting it would mean running two pipelines. It also wants Python ≤3.11
  against our 3.13, and is GPL. Worth reading for algorithms.
- **AFMReader, pySPM** — file readers, and Gwyddion already reads everything
  through the bridge we have.
- **driftcorrection** — lattice-based distortion correction, which Gwyddion
  already provides as affine correction, drift compensation and polynomial
  distortion.

The shape that survives is three pieces and no more: **Gwyddion for reading
and heavy processing, igor2 for the Asylum note, and our own thin layer for
judgement and orchestration.**

## What it unlocks next

`Acquisition.noise_spacings()` now computes what
[[mains-noise-has-a-computable-spacing]] described: scan speed over frequency,
so 3.744 µm/s at 50 Hz gives 74.9 nm. That is the discriminator the real-space
sweep in `features.periodicity` is waiting for before it can be switched on.

Sessions are dated too — twelve of them in the training set — which is what
lets one calibration scan speak for every other scan taken beside it.
