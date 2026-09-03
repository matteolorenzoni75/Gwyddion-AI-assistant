---
title: Mains noise has a computable spacing, so it can be told from a pattern
tags: [artifacts, periodicity, noise, metadata, scan-speed, quality]
verified: 2026-09-03
confidence: measured
---

The user's instruction: *"attenzione a non confondere rumore con periodicità
del pattern, qui ci deve essere un discrimine, di solito il rumore elettrico è
50Hz, più possibile rumore meccanico, ricordati che hai i metadati sulla
velocità di scansione."*

That is not a heuristic. It is arithmetic, and it turns the hardest judgement in
the periodicity measurement into a comparison of two numbers.

## The arithmetic

A disturbance at a fixed **temporal** frequency writes a fixed **spatial**
period into the image, because the tip moves at a known speed:

    spacing = ScanSpeed / frequency

Measured from a real file in the pool (`ALEX_AS_SGHS_Br_I0019.ibw`):

| field | value |
| --- | --- |
| ScanSpeed | 3.744 µm/s |
| ScanRate | 0.2496 Hz (lines/s) |
| ScanPoints × ScanLines | 512 × 512 |
| FastScanSize | 6 µm |
| ScanAngle | 90° |
| IntegralGain | 14.014 |
| DriveFrequency | 71358 Hz |

So mains interference at 50 Hz lands at **74.9 nm**, and its harmonics at
**37.4 nm** (100 Hz) and **25.0 nm** (150 Hz).

Compare that with the candidates the periodicity search kept producing on the
DVD scan before the fix: 39.7, 45.5, 48.1, 51.1, 54.0 nm — all of them at
about 90°, which is along the fast axis. They sit in exactly that family. It
was never structure.

## Two things that make it safe to use

**Direction.** Mains noise rides on the fast scan axis and only there, because
that is the axis time maps onto. `ScanAngle` says where that axis points. A
repeat at the noise spacing but running across the fast axis is not noise.

**A warning against using period alone.** At this scan speed 74.9 nm is also
the pore pitch of the anodic porous alumina in
[[the-sample-library-is-the-exam]], certified at 74 nm. A rule that rejected
everything near 74.9 nm would throw away a real structure with a certified
answer. Period *and* direction together, never period on its own — and when
both match, say so rather than deciding silently.

Mechanical noise has no single frequency, but the same reasoning applies to any
line the user identifies: convert it to a spacing with the scan speed and
compare.

## The obstacle: conversion throws the metadata away

The raw Igor waves carry all of the fields above. The `.gwy` files our bridge
produces from them carry **zero metadata keys**. Until that is fixed none of
this is computable at run time, which is why the real-space sweep in
`features.periodicity` is switched off by default: without the noise
discriminator it costs more in false positives than it buys in recall.

Fixing the bridge to preserve the scan note is therefore not housekeeping. It
is the thing that unlocks the discriminator, and with it a good part of the
image-quality judgement too — `IntegralGain` and `Setpoint` are what a
badly-tuned feedback shows up in.

## Related

An artificial pattern and a natural one are different in kind — the user said
so in the same breath. A lithographic grating repeats to the tolerance of the
mask; a grain structure has a preferred spacing with a wide spread. The
confirmation value in `periodicity` already separates them in practice: the
calibration grating scores 1.90 out of 2, while every natural surface in the
pool that showed any repeat at all sat between 0.5 and 0.65.
