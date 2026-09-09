---
title: The drag belongs to the object, not to the background
tags: [masking, levelling, tip, artifacts]
verified: 2026-09-07
confidence: measured
---

# The drag belongs to the object, not to the background

When the tip carries material -- or simply lags behind the surface it is
tracking -- an object leaves a streak behind it along the fast scan axis. The
streak is a small fraction of the object's own height, far below any threshold
that finds the object itself, and so it is left out of the mask and counted as
background.

It is not background. A median of differences works row by row, and every row
that crosses the tail has its median lifted by the tail. The correction then
writes that lift into the surface: the flattening makes the image worse
exactly where the object is, which is where anyone will look.

The user's note, which is what put this in:

> questa operazione è valida anche con oggetti multipli che hanno uno spiccato
> trascinamento

So the mask has to follow the drag, and with several objects it follows each
of them. Two things make that safe:

**Grow along the line, never across it.** A tail runs with the fast axis by
construction. An isotropic growth from the same seeds, tried earlier, swallowed
81% of the frame and left the base no flatter than untouched; the directional
one adds between 0.1% and 9.7% across this batch and never runs away.

**Stop twice over.** The growth stops where the surface comes back to within
1.5 noise widths of the background, and in any case after 15% of the scan
width. The second bound is what stops a deliberately low bar from walking the
whole scan line on a quiet substrate -- and a mask that reaches the frame edge
has stopped describing an object.

Measured on the batch: the drag-aware mask moved 24 more scans onto the masked
route (60 -> 84) and took the over-flattened count from 3 to 2.

See also: `what-the-operator-must-be-asked.md` -- following the drag is a
correction to the *background fit*, which is why it is applied without asking.
Removing the object itself is not, and never will be.
