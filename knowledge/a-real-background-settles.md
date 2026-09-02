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

The rule: take the lowest order that accounts for at least 10% and whose
successor adds less than 5 percentage points. If nothing settles, a plane is
still defensible — tilt is a real acquisition artifact with a physical cause —
but only if it accounts for something; higher orders in that case would be
cutting into the sample.

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
