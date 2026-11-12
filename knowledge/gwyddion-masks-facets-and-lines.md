---
title: Gwyddion masks are geometry, not only a height threshold
tags: [gwyddion, masking, facets, line-correction, operator-targets]
verified: 2026-09-10
confidence: documented
---

# Gwyddion masks are geometry, not only a height threshold

The target of a mask is the region that must not decide what the background
is.  It is not necessarily the region above a global height threshold.

The Gwyddion user guide documents several ways to create it:

- grain marking by **height, slope or curvature** threshold;
- **watershed** or segmentation, useful when a threshold does not separate
  complicated structures;
- masks from **edge/correlation/facet** analyses;
- manual Mask Editor operations: set, add, subtract, intersect, fill, grow and
  shrink; and morphology (opening/closing) to simplify a mask.

Sources: [Masks](https://gwyddion.net/documentation/user-guide-en/masks.html),
[Grain analysis](https://gwyddion.net/documentation/user-guide-en/grain-analysis.html).

## What follows for AFM Copilot

1. The height mask remains one *candidate*, never the whole recognition
   system.  The operator-corrected pairs are supervisory evidence for cases
   where shape, edge or directional response must enlarge, split or reject it.
2. For a raised object on a flat base, keep the accepted mask while fitting the
   background.  Gwyddion's polynomial background and line-correction tools can
   exclude masked pixels; the fit is then based on the unmasked area.  It is
   still valid to subtract the fitted background from the complete image.
3. Before masked row alignment, inspect the unmasked support in **each** row.
   A global mask share is insufficient: rows without background produce
   invented offsets.  A target pair must demonstrate a safe result before an
   automatic route is enabled.
4. When an automatic mask is uncertain, preserve the map and request a manual
   mask rather than flattening a possible nanoparticle.

Sources: [Levelling and background subtraction](https://gwyddion.net/documentation/user-guide-en/leveling-and-background.html),
[Scan-line artefacts](https://gwyddion.net/documentation/user-guide-en/scan-line-defects.html).

## Facets and terraces

**Level → Facet Level** finds a plane that makes prevalent facets horizontal.
It is the preferred operation for distinct flat levels/terraces, and supports
including or excluding masked pixels.  It is not appropriate for random,
finely noisy or non-topographic data.  The app must therefore require both
distinct histogram levels and locally flat plateaux before selecting it.

Source: [Gwyddion Facet Level](https://gwyddion.net/download/user-guide/gwyddion-user-guide-en.pdf).

### A step must not decide the plane used to reveal the step

The first implementation searched the raw height histogram only.  It routed
none of the six blind-corpus scans retained as terrace references to Facet
Level.  A conventional least-squares plane was not a safe preconditioner: a
large step pulls that plane towards itself and turns the plateaux into ramps.

The conservative fallback now estimates the prevalent facet from **local
gradients**.  After light smoothing, it discards the steepest 20% of gradients
(edges, particles and scars), takes the median remaining x/y slope, and removes
only that plane for the purpose of recognition.  The output image is untouched;
Gwyddion still performs the eventual Facet Level operation.

Measured over all 44 kept blind scans, the fallback produced two or more height
populations on five scans.  The independent per-population flatness test
accepted only `scan-043`, the visually unambiguous broad two-plateau case.  It
rejected the compact particle layers `scan-028` and `scan-029`, as well as four
ambiguous histogram candidates.  The resulting routing change is deliberately
small: one scan moved from masked object levelling to `facet-terraces`; the
other 43 routes did not move.  Synthetic regression tests cover both a tilted
three-level surface and a dense particle layer.

## Manual correction as target, not an exception

The Mask Editor is a first-class route in Gwyddion.  An operator-drawn mask is
not a failure of automation: it is the reference from which the app can assess
its proposed mask, background residual and row-correction decision.  It must
never be confused with an authorisation to interpolate or remove the marked
object itself.
