---
title: A real background settles; chasing the surface keeps climbing
tags: [background, polynomial, decision, over-processing, levelling]
verified: 2026-09-02
confidence: measured
---

The polynomial order for a background correction can be chosen from the scan
instead of set in advance, and the signal that works is not how much the
leftover roughness falls.

## What does not work

Choosing the order by how much it reduces the residual. Removing a genuine
background and carving into real surface structure both reduce it, so the
criterion cannot tell them apart. Applied to the six test scans it gave order 3
to a surface the instrument had already levelled — every extra order kept
finding something, and what it was finding was the sample.

## What works

Measure how much of the height variation the fitted background *accounts for*,
at each order, and look for the point where it stops growing. A real background
has a definite shape: once it has been captured, a higher order finds no more
of it. Fitting the surface itself never settles.

| Surface | order 1 | order 2 | order 3 | |
|---|---|---|---|---|
| synthetic tilt | 99.9% | 99.9% | 99.9% | settles → order 1 |
| synthetic bowl | 0.0% | 99.1% | 99.1% | settles → order 2 |
| real, tilted (DVD) | 58.6% | 58.8% | 59.1% | settles → order 1 |
| real, already levelled | 0.0% | 46.3% | 64.9% | never settles → none |

The last row is the case that matters. Its plane accounts for nothing, and
every higher order keeps climbing — the mark of a fit finding structure rather
than form.

## Settling has to be measured against what is left

The first version of the rule asked whether the next order added at least five
percentage points *of the whole*, and that went blind wherever the background
was already nearly perfect. On a polished substrate order 1 accounted for
99.59% and order 2 for 99.95%: the extra 0.36% looked negligible, order 1 was
chosen, and an 18 nm bow stayed in the image — on a surface whose noise is
0.7 nm. That 0.36% was **88% of everything still unexplained**.

So the test is relative: the next order must account for less than 15% of what
remains. Which then needs two guards, because two situations look alike once
you allow the fit to keep climbing.

**Curvature must earn more than tilt does.** A tilted sample has a physical
cause — how it sits on the stage. Curvature is as often the shape of the sample
itself. So an order of 2 or more is only accepted when it accounts for at least
60%: on a frame holding three large domes, order 2 accounts for 41%, and taking
it would carve the domes out of the image.

**And when nothing settles at all, ask whether a low order still dominates.**
This is what separates the two hard cases:

- *Flakes on mica*: order 1 accounts for 34%, order 2 for 88%, and nothing
  settles by order 3. Order 2 **is** the background whether or not higher
  orders keep improving on it. The old rule fell back to the lowest order and
  left the bow in.
- *Already levelled by the instrument*: 0%, 46%, 65% — no order reaches a
  majority, because the polynomial is tracking the sample. Correctly left
  alone.

The threshold between them is 80% of the height variation. Above it, a
background; below it, the surface.

**The rule, in full:** take the lowest order that accounts for at least 10% —
and, from order 2 upward, at least 60% — whose successor adds less than 15% of
what is still unexplained. If nothing settles, take the lowest order that
accounts for 80% or more. Failing that a plane is still defensible if it
accounts for something, and otherwise leave the scan alone.

Checked against every case with a known answer: four built surfaces (plane,
bowl, saddle, already-levelled) and eight real scans. All twelve correct.

## Two traps found while building this

**Do not step up one order at a time and stop at the first that does not help.**
A symmetric bowl gains nothing from a plane — the best plane through it is
horizontal — so that rule stops at order 0 and never reaches the order 2 it
needs.

**Look for objects only after removing the background.** Objects stand above
the background, not above the raw surface. Searching the raw surface marks the
high side of a tilt and the raised rim of a bowl as objects, and the background
is then fitted around the very shape it exists to remove. Two passes settle it:
rough background out, find the objects, refit without them.

## What this produced

On the six test scans the recommendation is now correct on all six, including
the two the instrument had already levelled, which are left alone. `plan` shows
the reasoning without processing anything.
