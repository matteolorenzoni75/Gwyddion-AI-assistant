---
title: What "vouched for" actually costs
tags: [batch, robustness, quality, levelling, guarantees]
verified: 2026-09-03
confidence: measured
---

The charter asks for a batch that comes out *fruibile e garantita*
([[what-the-tool-is-for]]). Getting the stages to run was the easy half. The
other half was three failures that all had the same shape: **the pipeline
losing or damaging data while reporting success.**

None was visible from the output. All three were found by checking the batch
against arithmetic rather than reading it.

## 1. A crash took forty files, and said nothing

Some files kill the Gwyddion subprocess outright — an access violation inside
a format reader, exit `0xC0000005` — rather than returning an error. Conversion
ran in groups of forty, so one bad file destroyed forty, including files that
had converted perfectly the day before. And because `convert()` returned only
its successes, the other thirty-nine vanished without a word.

Two fixes, and the second matters more than the first:

- **A crash is not a verdict on the group.** Halve it and retry; the culprit is
  isolated in a handful of passes. Forty lost became one lost, and that one has
  a name — a Windows duplicate, `... (2)`.
- **Every input file appears in the report**, kept, set aside, or unreadable
  with a reason. A file that disappears silently is worse than one discarded,
  because nobody can disagree with it.

The arithmetic to check: inputs must equal kept + repeats + set aside +
unreadable. On the real folder, 151 + 30 + 4 + 1 = 186.

## 2. The cleaning was quietly destroying surface

Six scans in 128 came out with almost no roughness left, and the pipeline
called it success. The test is not judgement, it is arithmetic: **if a fitted
background explains a fraction f of the height variance, √(1 − f) of the RMS
should survive.** Far below that means surface was removed, not artifact.

Two mechanisms, both real:

- **Row alignment on a nearly flat surface.** `Nano Cellulose on Mica#2006` is
  0.9 nm RMS covered in small particles, with the heaviest row banding in the
  set. The median of a row's differences cannot tell a particle from a line
  offset, so it takes both. It kept 6.8% of its roughness where 97% was due.
- **Masking a pattern as though it were objects.** On `ebl pattern retrace` the
  lithographic pattern *is* the object, so marking it and levelling flattens
  the thing being measured.

**Flagged, never corrected automatically.** Which recipe is right depends on
what the sample is, and choosing one by rule of thumb is exactly how a scan was
ruined before, with the numbers agreeing all the way —
[[fixed-recipes-cannot-decide]].

## 3. The crop had to reach disk

Cropping happens in Python 3; the recipes run inside Gwyddion. Without writing
the trimmed frame back out, every cleaning step went on fitting backgrounds
through the empty band. `gwy_io.save_height` exists for that one reason.

## The rule that generalises

A pipeline stage that cannot fail loudly will fail silently. For each one, ask
what it does when its input is bad, and make sure the answer is written down
somewhere a person will see. The three checks that earn their place here are
cheap: **count the files, predict the roughness, and never let a subprocess
speak for more files than it can crash with.**
