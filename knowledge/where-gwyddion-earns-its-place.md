---
title: Where Gwyddion earns its place, measured rather than assumed
tags: [architecture, gwyddion, bridge, efficiency, duplication, decision]
verified: 2026-09-07
confidence: measured
---

The user asked the right question: if we cut Gwyddion out and did everything
here, would the results be as good, or worse? The instinct was that the bridge
— two runtimes, a Python 2.7 subprocess, chunking, crash isolation — was the
expensive part. **It is not, and the measurement reversed the answer.**

## What the batch actually spends, on 197 kept scans

| stage | time | share |
| --- | --- | --- |
| reading, judging, measuring — all Python 3 | 225.6 s | 67% |
| Gwyddion's cleaning recipes, through the bridge | 10.1 s | **3%** |
| drawing the final pictures | 98.6 s | 30% |

The bridge costs **0.05 s per scan**. Replacing it would have optimised the
part that was already free, and paid for it with 176 file readers and
algorithms the user's own community treats as the reference.

## So the boundary is not "less Gwyddion" — it is "neither of us twice"

**Gwyddion keeps** what it is authoritative for: reading files, and the
operations where its implementation *is* the reference — scars, watershed
grains, tip work, affine and drift distortion. And one more thing that is not
technical and matters anyway: a number the user can reproduce by opening the
file themselves is worth more than one only this tool can produce. For a tool
promising *misure garantite*, that is the property, not a convenience.

**We keep** measuring, judging, deciding, laying out. Gwyddion has no opinion
about those.

**Neither does the same work twice**, which is where the real fault was.

## The duplication the timing exposed

Counting the calls on one 512-square scan: the background was **chosen five
times and fitted twenty**, across `plan_for`, `measure`, `assess` and the tip
bound. Each stage worked it out for itself.

The cost was the obvious half. The other half is worse and had gone unnoticed:
the four stages were describing **four slightly different levelled surfaces of
the same scan**. The roughness reported for a scan and the picture drawn of it
did not necessarily agree.

`decide.Levelling` now carries one levelling from the plan into everything
downstream. Measuring and judging fell from 225.6 s to 193.2 s — 14%, not the
larger number hoped for, because `assess` runs before a plan exists and the
object-background iteration inside `plan_for` is inherent to it. The
correctness fix is the part worth having.

## The rule to keep

Before optimising a boundary, price it. The bridge *looked* expensive because
it was where six bugs happened in a single day — a crashing file taking forty
with it, `gwy` against `output`, `input` against `source`, dropped metadata,
two broken tip functions. **Bug frequency is not cost**; those were cheap to
fix once found, and the boundary they sit on buys a great deal.
