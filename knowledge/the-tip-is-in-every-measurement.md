---
title: The tip is in every measurement
tags: [artifacts, tip, convolution, dilation, grains, gwyddion]
verified: 2026-09-02
confidence: stated-by-user
---

An AFM image is not the surface. It is the surface **dilated by the tip**: at
every point the instrument records the highest contact between a finite probe
and the sample, so anything sharper or narrower than the tip comes back with
the tip's own shape written into it.

The user raised this twice while labelling, unprompted, on two different
samples:

- On the nanoparticles on silicon (`RZ6 mono Molinaro017`): *"probabilmente
  qualche artefatto per la punta deformata"* — a damaged or double tip.
- On the oxide grains (`SINPYs`, three scans): *"possibile effetto convoluzione
  dovuto alla geometria della punta"*.

That it came up on two of about a dozen labelled samples says how routine it
is. It belongs in the pipeline, not in a footnote.

## What it does to the numbers we already compute

- **Widths are overestimated, depths underestimated.** A round particle of
  radius r imaged with a tip of radius R comes back about 4·sqrt(rR) wide. The
  object-size statistics are systematically too large, and by an amount that
  depends on the tip, not the sample.
- **Narrow pits fill in.** The tip cannot reach the bottom of a hole narrower
  than itself, so a porous surface reads as shallower and smoother than it is —
  which touches the pitted scans (4, 10, 11) directly.
- **A double or chipped tip repeats a shape.** The same asymmetric outline
  appearing on every object in a frame is the signature, and it is one of the
  few positive reasons to call something an artifact under
  [[a-wrong-label-costs-more-than-no-label]]. One odd-looking object is not
  evidence; the same odd shape on all of them is.

## What Gwyddion already offers

The tools exist and are reachable from PyGwy; none of this needs to be written
from scratch.

- **Blind tip estimation** from the image itself — it recovers an upper bound
  on the tip shape from the sharpest features present, with no calibration
  sample.
- **Surface reconstruction (erosion)** — undoes the dilation as far as the data
  allow.
- **Certainty map** — marks which pixels the tip could actually have touched.
  This is the honest part: where the map says the tip never reached, the
  reconstruction is a guess, and those pixels should be excluded from any size
  statistic rather than quietly included.
- **Tip modelling** — synthesises a tip of known geometry, which is also the
  route to realistic synthetic training data.

## The rule to apply

Never present a lateral size as if it were the sample's. Either deconvolve and
say so, or report the measured width together with the note that it includes
the tip. A depth measured in a narrow feature carries the same caveat.

Height perpendicular to the surface is largely unaffected — which is another
reason the step-height measurement on a scratch ([[interrupted-scans-should-be-cropped]]
lists two more of those in the pool) is the most trustworthy number the
instrument gives.
