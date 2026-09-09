---
title: Two thresholds that never met left a fifth of the batch unmeasured
tags: [roughness, masking, thresholds, recognition]
verified: 2026-09-09
confidence: measured
---

# Two thresholds that never met left a fifth of the batch unmeasured

The whole-frame roughness needs under **3%** of the frame in objects. Counting
objects needs at least **five** of them. Both bars were set for good reasons,
years apart in the code, and nobody checked that they touched.

They do not. A substrate with three specks on it is too busy for the first and
too empty for the second, and **24 scans of 199** sat in that gap with no
measurement at all. It looked like a property of the samples. It was an
accident of arithmetic.

## The fix is not to move either bar

Widening "uniform" to 10% would let real particle fields be called uniform;
lowering "enough objects" to two would let two specks be called a population.
Both bars are right for what they guard.

What was missing is a third answer, and it is the one the operator actually
wants for such a scan: **how smooth is the background**. The objects are
excluded rather than tolerated, with the same mask that keeps them out of the
levelling, grown two pixels further because the skirt around an object is the
tip's own shape.

    scans with no family    38 -> 27

## The second half of the fix

Ten scans stayed behind, and the condition that held them was
`bimodality < 0.50` -- "the heights do not look split". That was the wrong
test. Their histograms *do* look split, the step routine examined them and
**refused**, and a refusal there says *one population, not two*. Which is
exactly the case where the roughness of that one population is the right
answer.

The condition became "no step was reported" rather than "the heights did not
look split":

    scans with no family    27 -> 17
    in the gap              24 -> 3

The three that remain have their background masked past the point where a
roughness means anything, and they stay unnamed.

## The general shape of this

Both halves are the same mistake: a rule reading a raw signal when it should
have been reading **what the previous rule concluded**. `bimodality` is an
input; "we could not find a step" is a result. Rules that chain off each
other's conclusions need far fewer thresholds than rules that each re-derive
the world from the pixels.

See also: `a-wrong-label-costs-more-than-no-label.md`,
`a-level-is-a-peak-that-comes-back-down.md`.
