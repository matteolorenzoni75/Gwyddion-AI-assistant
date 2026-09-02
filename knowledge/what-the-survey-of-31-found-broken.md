---
title: Three measurements that fail, found by reading 31 scans one by one
tags: [periodicity, objects, cropping, background, descriptors, defects]
verified: 2026-09-02
confidence: measured
---

A blind survey of the 31 scans that the descriptors do not separate. Six were
identified by the user; the rest were read from the images. The point of the
exercise was not the labels — it was that looking at each image beside its own
numbers exposes failures that no aggregate ever shows.

## 1. Six of thirty-one scans stop partway

Indices 9, 13, 22, 23, 24, 26 — between 27% and 89% of the frame carries no
data. See [[interrupted-scans-should-be-cropped]]. A fifth of the pool, and
until they are cropped every descriptor on them is measured partly on a dead
band, which drags everything toward "smooth" in proportion to how early the
scan stopped. This is very likely one reason the group does not separate.

**And the detector for it was wrong.** The first version took the median of the
row-to-row spread as its idea of a live row. When more than half the frame is
dead the median *is* zero, so the test disabled itself — it found three of the
six, missing exactly the three that were worst (89%, 68%, 56% empty). The
ninetieth percentile asks the right question — "what does a live row look
like" — and finds all six.

## 2. Periodicity fails in two distinct ways

- **A single straight edge reads as a repeat.** On the scratch scan (index 2)
  one groove crossing the frame scores 28, well above the 3–4 of a random
  surface. A straight edge across the whole frame resembles a stripe of very
  long wavelength.
- **It locks onto the two-pixel limit.** On indices 3, 12, 20, 21, 25 and 27 it
  returns a "period" of a little over two pixels — the physical limit below
  which an image describes nothing. It is measuring line noise.

The case that matters most is index 12, an optical disc surface: the most
plainly periodic image in the set, and the measurement returns noise instead of
the track pitch. Index 25, a regular dot lattice, fails the same way.

Two conditions would remove both failures: the peak must repeat at least three
times inside the frame, and the period must be at least four pixels.

**A caution recorded with it:** a quick autocorrelation check written to verify
the pitch was also wrong — along the lines of a grating the correlation stays
high at every distance, so the peak lands on the first radius and a grating
reads as 547 nm. Both routes need care; neither is a free second opinion.

## 3. The object count only looks upward

It finds what stands above the background. On pitted surfaces (4, 10, 11) it
reports zero objects against dozens of obvious holes — a porous surface and a
perfectly smooth one look identical to it. Height asymmetry separates them
easily (−1.97, −1.51, −1.89 against +1.43 for a surface with grains on top),
so the information is there; the count throws it away.

Two further failure modes from the same survey:

- **Close-packed layers.** On 27, 28, 29 — spheres touching each other — it
  reports 4 and 7 pieces against thousands, because there is no background to
  stand above. This needs grain segmentation (watershed), not a threshold.
- **Very flat substrates.** On 30 and 31, polished surfaces, it claims 18% of
  the frame is objects. After removing 99.7% of the variation the threshold is
  working inside the noise. An object fraction is meaningless once the residual
  range approaches the noise floor.

## 4. The background order is wrong once, not ten times

Only index 16 is clear: order 1 explains 34% of the variation, order 2 explains
88%, and 1 is chosen. The rule falls back to the lowest order when no order
settles, and here settling never arrives within degree 3.

**The first count of this was ten cases, and it was wrong** — the check had been
run without the mask, while the real pipeline excludes objects before fitting.
Re-run through the real path, five cases are arguable and one is clear. On 2, 3
and 21 the low order is probably right: there is no background to remove there,
there is an object, and a higher order would carve into it. See
[[a-real-background-settles]].

## 5. Two more duplicate pairs

28 with 29 at r = 0.9998, and 30 with 31 at r = 0.9973 — the same area
rescanned. The exact-fingerprint check in [[six-scans-were-filed-twice]] missed
them because the pixels differ very slightly. A group that forms on a duplicate
pair is not a group; it is one image counted twice.
