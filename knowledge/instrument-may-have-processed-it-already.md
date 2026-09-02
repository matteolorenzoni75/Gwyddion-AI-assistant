---
title: Some scans arrive already levelled by the instrument
tags: [provenance, tilt, levelling, training-data]
verified: 2026-09-02
confidence: measured
---

A file straight from the microscope is not necessarily raw. Some arrive with a
plane fit or a filter already applied by the instrument's own software, and
nothing in the filename says so. Processing them again is at best wasted and at
worst harmful.

Two independent signals answer it, and they agree.

## The measured tilt

How much of the height variation a single fitted plane accounts for. Across the
six test scans:

| Scan | Tilt |
|---|---|
| four of them | 81%, 59%, 37%, 26% |
| two of them | **0%, 0%** |

Zero is not a small number here, it is a categorical one: a genuinely raw scan
essentially never has exactly no plane component. The two zeros were the two
whose instrument had levelled them, and running the levelling recipe on them
changed the roughness by 0.00%.

## Gwyddion's own log

Every file Gwyddion saves carries a log of what was done to it. A file that was
only read shows one entry naming the importer:

    file::psia(filename="...")

Anything after that line is processing. This also identifies the importer that
read the file, which is how the vendor of a bare `.tiff` becomes known — `psia`
is Park Systems.

## Why this matters for training

Learning what a raw scan needs requires knowing which scans are raw. A set that
mixes untouched and pre-levelled files will teach that levelling does nothing,
because for a large fraction of the examples it correctly does nothing.

So the tilt measurement is the first filter to run over any new material before
it is used to learn from, not a diagnostic to consult afterwards.
