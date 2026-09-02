---
title: A masked polynomial fit leaves raised objects intact
tags: [masking, background, polynomial, flattening]
verified: 2026-09-02
confidence: measured
---

Gwyddion's polynomial background *is* subtracted from the whole image, but it
can be *fitted* on the background alone. Give the channel a mask covering the
raised objects and set the module's `masking` parameter to 0 (exclude), and the
marked pixels take no part in the fit.

## What was measured

A synthetic surface: a bowl-shaped background 50 nm deep, with a perfectly flat
square object 200 nm tall covering 12% of the frame, plus 0.3 nm of noise. A
second-order polynomial background was then removed two ways.

| Fit | Object's flatness afterwards |
|---|---|
| Over the whole image | 8.364 nm |
| With the object masked out | 0.300 nm |

The object began flat to within the 0.3 nm noise. Fitting through it distorted
it by 28 times that; fitting around it left it exactly as it was.

## Why it matters

This removes the usual objection that a polynomial background "acts on the
whole image and therefore cannot be used when there are objects on the
surface". Subtracting from the whole image is correct — the background is
underneath the objects too. What must not happen is the objects taking part in
deciding what the background *is*.

## How to reach it

The `isolate-objects` recipe: level roughly, mark what stands above the surface
by height threshold, discard the specks, fit the background with the mask
excluded, drop the mask, align rows, set the zero.

## What is still unsolved

The polynomial *degree* is fixed in the recipe and should not be. Applied to a
real scan whose background measured 0% tilt — already levelled by the
instrument — a second-order fit invented curvature at the corners that was not
there. The masking was right and the degree was wrong.

Choosing the degree from the measured curvature of the background, rather than
setting it in advance, is the open problem. See
[fixed-recipes-cannot-decide](fixed-recipes-cannot-decide.md).
