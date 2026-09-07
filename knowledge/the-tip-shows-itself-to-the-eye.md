---
title: A worn tip is obvious to look at and hard to measure
tags: [tip, artifacts, quality, recognition, two-routes, failed-attempts]
verified: 2026-09-07
confidence: measured
---

The user asked whether the software recognises a deteriorated tip — the
characteristic teardrop or triangle blobs. It does not, and four attempts to
make it failed. This records what they were and why, so nobody spends the
afternoon again.

## What it looks like

Unmistakable. On `tip artifact retrace` and `121127-Topography-005` every
object in the frame is the **same triangle**, and often pointing the same way.
A pyramidal tip whose apex has broken off no longer measures particles; its
facets image themselves onto everything smaller than the truncation. Ground
truth from the user for six scans: `tip artifact retrace` / `trace` and
`121127-Topography-005` (truncated, blunt), `RZ6 mono Molinaro017` (deformed),
and three `SINPYs` scans (tip-geometry convolution).

## Four measurements that did not work

1. **Shared orientation of the objects.** Independent objects have no reason to
   point the same way, so alignment should betray the tip. It fired on 12% of
   the batch and caught one of the six — because the things it found were
   samples that genuinely are aligned: optical disc tracks, fibres.
2. **Shared orientation *and* shared outline**, comparing object images by
   correlation. Down to 5% of the batch, still one of six. `tip artifact
   retrace` scored 0.11.
3. **Facet symmetry of the surface gradients** — no segmentation at all, asking
   whether the slope directions pile up at 120° or 90° spacings the way three
   or four flat faces would. The flagged scans scored 0.26–0.35 while the
   highest scores in the batch, 0.47–0.59, belonged to *interrupted* scans,
   where the dead constant band makes the gradients degenerate.
4. Implicit in all three: **they need objects on a background.** On
   `121127-Topography-005` the triangles fill the frame and there is no
   background at all, so the detector finds nothing and every statistic built
   on it reads zero.

## Why this matters beyond the tip

This is the clearest case yet for [[two-routes-for-every-judgement]], and it
falls the way the user's rule anticipated: **the deterministic route cannot see
it and the model looking at the image can.** Reading the six scans took one
glance; three statistics and a morning did not get there.

So the tip check belongs on the learned side for now, with the measurements
supporting rather than deciding. Nothing was shipped: a detector that catches
one case in six and flags optical discs would be worse than none, by
[[a-wrong-label-costs-more-than-no-label]].

## What would actually work

**A reference sample, not a cleverer statistic.** Gordon et al. 2024 classified
tip state by normalised cross-correlation against a template of what an ideal
tip produces — which needs a known sample, not an arbitrary image. See
[[simple-transforms-beat-deep-networks-here]] and the certified samples in
[[the-sample-library-is-the-exam]]: a calibration grating imaged at the start
of a session characterises the tip for every scan that follows it, the same way
a DVD dates the scanner's calibration in
[[lateral-distances-need-two-corrections]].

Gwyddion's **blind tip estimation** is the other half: it recovers an upper
bound on the tip shape from the sharpest features already in the image. Compare
that estimate against the tip's nominal geometry and the discrepancy *is* the
wear, measured rather than inferred. That is the route to take when this is
picked up again — see [[the-tip-is-in-every-measurement]].
