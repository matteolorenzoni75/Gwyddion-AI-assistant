---
title: An interrupted scan is cropped, not discarded
tags: [artifacts, cropping, scan-defects, training-data]
verified: 2026-09-02
confidence: observed
---

Several scans in the pool stop partway down: the tip loses contact or the scan
is aborted, and the remainder of the frame is a flat uniform band carrying no
data. At least six of the 31 in the central group are like this — in some,
half the frame is empty.

**The correct handling is to crop to the part that is real and treat it like
any other scan**, at the user's instruction. Not to discard it: the measured
part is good data, and throwing away half a pool this size is not affordable.

## But there is a point where cropping is not worth it

Reviewing the six, the user cropped five and discarded one. The one discarded
(`Silaver Film - Kiril 20nm001`) has **89% of the frame empty** — a few rows
survive. The ones kept were 68%, 56%, 38%, 31% and 27% empty, including two
that carry a film-thickness scratch worth measuring.

So the rule is not "always crop". It is: crop while enough of the frame
survives to contain something measurable, discard when it does not. On this
evidence the boundary sits somewhere between 68% and 89% empty; **keep when at
least about a third of the frame survives** is a defensible working rule, and
the decision should be shown to the user rather than taken silently — the
question "is what is left worth measuring" depends on what is in it.

## Why it mattered here

Before this was noticed, the empty half was being measured as though it were
surface. A flat band has no roughness, no periodicity and no objects, so it
drags every descriptor toward "smooth and featureless" in proportion to how
much of the frame it covers. Scans of quite different materials ended up close
together because they were interrupted by similar amounts.

That is very likely part of why the central cloud did not separate: the
measurements were partly describing *how far the scan got*, not what was on the
surface.

## What detection looks like

The dead region is not merely flat — it is *constant*, or very nearly so, and
it occupies whole rows at one end of the frame. So: work down the rows from
each end, and find where the row-to-row variation collapses to near zero
compared with the middle of the image. That boundary is where the scan stopped.

Cropping must keep the physical scale: the retained region's real width and
height have to be recomputed from the pixel count, or every size measured
afterwards is wrong.

## Related

The user notes scans range from 0.5 to 60 µm in practice, and the software
should handle 10 nm to 100 µm. The same structure is often imaged at several
zooms, so a cropped scan and its parent may both be present.
