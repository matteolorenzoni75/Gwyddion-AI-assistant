---
title: The z feedback curves the background around tall objects
tags: [artifacts, background, levelling, masking, feedback, scanner]
verified: 2026-09-02
confidence: stated-by-user
---

The curved, banded background seen around a tall feature is usually **not the
sample's shape and not scanner tilt**. It is the z feedback loop settling.

User's words, on the perovskite crystal scan (`AS_SG_Mix_Br_I_10005`): the
background curvature is *"dovuto al fenomeno di landing o fly del feedback su
z, questo è quello che poi dobbiamo correggere"*.

## The mechanism

The loop that holds the tip on the surface has a finite response time. When the
tip climbs onto a tall object, the loop lags, then overshoots, then relaxes —
and that relaxation is written into the pixels that follow, **along the fast
scan direction**. Dropping off the far side does the same in reverse. The same
thing happens on landing at the start of a scan, bowing the first part of the
frame.

Two consequences that matter for how we correct it:

- **It is directional.** The distortion runs along the fast scan axis, because
  that is the axis time maps onto. A background that is genuinely the sample or
  the scanner has no reason to prefer one axis.
- **It is caused by the objects.** The curvature is worst next to tall
  features and absent in open flat areas. So it correlates with exactly the
  pixels that must be left out of any background fit.

## How to correct it

This is what the masked fit was built for: mark the objects, fit the background
on the remaining pixels only, subtract from the whole image. See
[[masking-lets-the-background-be-fitted-alone]] — measured there as 8.364 nm of
distortion down to 0.300 nm.

Because the artifact follows the fast scan direction, a correction that works
line by line along that axis fits it more closely than an isotropic polynomial.
But line-by-line levelling costs more roughness than image-wise levelling — by
Nečas, roughly a factor 1/α worse — so it is not free, and Sq measured after it
must carry that caveat. Prefer the plain masked polynomial unless the residual
shows the artifact is genuinely per-line.

## What not to conclude

A curved background is not evidence that the sample is curved, and removing it
is not "flattening away real data". It is removing the instrument's response
from the instrument's measurement. The check that it worked is that the
background around the object becomes as flat as the background far from it.
