---
title: Semantic morphology reviews may restrict but not authorise processing
tags: [recognition, masking, grains, vision, safety, levelling]
verified: 2026-09-21
confidence: measured-on-blind-corpus-and-regression-tested
---

# Semantic morphology reviews may restrict but not authorise processing

## Finding

A close-packed granular surface can leave a minority of low or high pixels
after background subtraction and therefore look numerically like isolated
objects or pores.  It does not follow that the remaining majority is a flat
background on which masked row correction or polynomial levelling is valid.

The external `Stechio MA5035` probe and blind corpus `scan-053` both show
continuous granular morphology under a large acquisition slope.  Before
semantic review, the planner called the first one objects on a flat background
and `scan-053` had already lost more morphology in cleaning than its background
could account for.  By eye, neither contains the broad, uniform background
that interpretation requires.

## What was measured before changing the rule

A corpus-wide survey compared tile texture coverage, local high-pass skew at
several scales, extrema density, automatic object fraction, correlation length
and tilt.  The probe had full texture coverage, 8.2% apparent sunken objects,
97 px correlation length and 81% plane contribution.  `scan-053` had 89%
texture coverage, 12.3% apparent sunken objects, 114 px correlation length and
95% plane contribution.  But individual true-pit and smooth-slope scans overlap
these descriptors.  No single measured threshold cleanly separated the
semantic cases, so adding one would only move the false decisions around.

## Decision

An explicit visual or operator review can mark a scan
`granular_continuous` with effect `restrict`.  This does four things:

1. vetoes the automatic object mask;
2. vetoes polynomial background fitting;
3. vetoes row-by-row correction, even if its numerical diagnostic fires;
4. routes the scan to plane levelling and zeroing only.

The review cannot enable a mask, object removal, interpolation, facet
levelling or any stronger recipe.  A hand-drawn operator mask remains stronger
evidence and overrides the veto because it supplies an actual correction
target rather than a label.

The review source and family travel into `plan.json` and `batch.json`.  Invalid
families, effects, duplicate scan names and malformed evidence are rejected
instead of silently ignored.

The conversational interface follows the same contract through `plan_scan`:
after the model has received the rendered height map, it states only a family,
an advisory/restrictive effect and its visible evidence.  The deterministic
planner returns the permitted recipe and repeats the image for cross-checking;
it does not let the model bypass the safety rule by choosing operations
directly.

## Regression requirement

Tests must keep the asymmetry explicit: a restrictive continuous-morphology
review changes an otherwise masked object plan to `level-only`; an advisory
review changes nothing; and an operator mask still selects masked background
levelling.  The explanatory text must never claim that row correction or a
higher-order fit will run when the conservative recipe forbids them.
