---
title: Six scans in the pool are the same file under two names
tags: [training-data, duplicates, blind-evaluation, provenance]
verified: 2026-09-02
confidence: measured
---

Of 55 scans in the working pool, **six pairs are identical pixel for pixel**.
The pool holds 49 distinct scans, not 55.

| filed as | also filed as |
|---|---|
| `231219007006` | `Calibration grating - Vertical` |
| `AS_SGHS_Br_I0000` | `Single object high z step 3` |
| `AS_SG_Mix_Br_I_10005` | `Single object high z step 1` |
| `Camilla sample - deatil 02 5 um 001` | `Porous random sample` |
| `DVD240227010005` | `Porous Alumina` |
| `Noisy HOPG 2` | `SKPM_HOPG_TEST0010` |

Confirmed by hashing the height data itself, not by comparing filenames or
sizes.

## Why it matters more than it looks

Two of these pairs carry names that describe **different materials**. A DVD and
porous alumina are not the same sample; neither are a porous random sample and
a detail of Camilla's sample. Whatever happened, the names cannot both be
right — and one of them is being used to describe data it does not belong to.

Had the pool been labelled from filenames for training, the result would have
been an explicit instruction that a DVD and porous alumina look identical.
Which they do, in that data, because it is the same picture.

This is the clearest argument yet for the user's own rule that the test set
must stay blind: the names were not merely uninformative, two of them were
actively wrong, and only measuring the pixels revealed it.

## How it was found

Not by looking for duplicates. The descriptors were being computed for the
first time and several rows came out identical across seven independent
measurements — banding, row steps, periodicity, angle, object fraction, object
count, correlation length. Identical values across that many unrelated
quantities is not coincidence.

## What to do with them

Keep one of each pair. The pool for learning is 49 distinct scans, of which 34
are genuinely raw — the rest arrived already levelled, see
[instrument-may-have-processed-it-already](instrument-may-have-processed-it-already.md).
Counting a duplicate twice would weight whatever it is toward being the
"normal" case.
