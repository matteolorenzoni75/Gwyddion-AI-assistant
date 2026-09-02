---
title: The descriptors separate one group cleanly and leave the rest in a cloud
tags: [recognition, descriptors, clustering, periodicity, objects]
verified: 2026-09-02
confidence: measured
---

Sixteen measurements were added — banding between scan rows, single displaced
rows, periodic structure with its direction and spacing, object count and size
and elongation, correlation length, and the shape of the height distribution.
Run over the 34 distinct raw scans, with no filename ever consulted.

## What works

**Periodic structure, at any angle.** Random surfaces score 3–4; clean stripes
score in the thousands; weak stripes buried in noise still score 35. The
calibration grating comes out at 90 degrees, which is correct — its lines run
vertically. This matters because periodic noise arrives at arbitrary angles and
a detector that only sees the scan axes is useless.

**Banding between scan rows.** The scan with the worst banding measured 0.91,
and it is the same one where row alignment later removed 90.6% of the
roughness. The measurement and the correction agree about which scan had the
problem.

**Objects.** Counts and sizes behave sensibly: hundreds of small objects on one
scan, a handful of large ones on another, and near-zero on bare surfaces.

**One group formed on its own.** Placing the 34 raw scans by their descriptors
alone puts three of them clearly apart from everything else — the three that
are many small objects on a flat base. Nothing told the software they were
alike.

## What does not work yet

The remaining thirty sit in one central cloud. Two principal components
account for 53% of the variation, and within that cloud a calibration grating,
a DVD, porous films and silver films are not distinguished.

So: the descriptors are enough to separate *objects on a substrate* from
*textured surfaces*, and not yet enough to tell one textured surface from
another.

## What had to be fixed to get here

The first periodicity measure compared the strongest point of the Fourier
spectrum against the spectrum as a whole. Every rough surface scored 70–80 and
looked periodic, because any natural surface carries far more energy at low
frequencies than at high — the strongest point was simply the largest of the
low-frequency terms.

Comparing it instead against the other **directions at the same spatial
frequency** fixed it. What marks a repeating structure is energy concentrated
in one direction at one spacing, not energy at low frequency.

Also: the tests initially shared one random generator, so each test's numbers
depended on which tests ran before it and a failure could not be reproduced
alone. Each generator now seeds its own stream.
