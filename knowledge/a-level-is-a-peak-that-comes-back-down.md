---
title: A level is a peak the histogram comes back down from
tags: [terraces, histogram, thickness, recognition]
verified: 2026-09-07
confidence: measured
---

# A level is a peak the histogram comes back down from

The user's rule for when terrace heights may be quoted:

> istogramma h ha due picchi gaussiani o 3, molto definiti, allora si voglio
> l'altezza delle terrazze/a

"Molto definiti" is the whole rule, and it has to be written down as
something measurable. Two obvious tests are not enough on their own:

- **peak height** -- reaches some fraction of the tallest peak
- **prominence** -- stands some distance above the valley beside it

Those two alone put **105 of 199 scans** in the terrace pile on this batch.
Half a batch of ordinary AFM does not have terraces. A shoulder on one broad
hump clears both tests comfortably.

What actually separates two levels from one population is the shape *between*
the peaks and the width of the peaks themselves:

**The valley comes back down.** Between two levels the histogram falls to at
most 55% of the smaller of the two peaks. Two populations meeting in a shallow
dip are one population with a bump in it.

**Each level is narrow next to the gap.** A peak's width at half height is at
most 75% of the distance to its neighbour. Populations as broad as they are far
apart do not have a step between them, they have a slope.

With those two added the count fell to **20 of 199** -- and one of the twenty
is a file whose name ends in `20nm005`, measured at **20.0 nm**. The
filenames are never read by any of this, so that is an independent check that
came for free.

Note what the tests do *not* use: any assumption about which surface it is,
any fit of Gaussians, any prior on the step height. A histogram either
separates or it does not.

See also: `a-wrong-label-costs-more-than-no-label.md`.
