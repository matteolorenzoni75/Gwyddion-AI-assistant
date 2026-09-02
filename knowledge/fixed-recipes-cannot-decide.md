---
title: A fixed recipe cannot judge a scan; it has to be chosen from the data
tags: [recipes, decision, roughness, over-processing]
verified: 2026-09-02
confidence: measured
---

Choosing a recipe by eye, one scan at a time, does not scale and is not
reliable — including when the person choosing has looked at the image. The
roughness number does not catch the mistake, because over-correction lowers it.

## What happened

On a scan of a flat square object on a substrate, `clean-with-features` was
chosen because there was clearly an object standing above the surface. The
result:

| | RMS |
|---|---|
| Standard clean | no change |
| Feature-aware clean | **−35%** |

By the number, a success. In the image, the object — which is flat — had become
concave, with a dark halo around it. `flatten_base` assumes the base beneath
the objects is flat; this background has genuine terraces, and the correction
read them as curvature to remove, taking real structure with it and deforming
the object.

The choice was wrong and the number agreed with it.

## What follows

1. **A fall in RMS is not evidence of improvement.** It is evidence that
   height variation was removed, which is what over-correction does.
2. **The image must be looked at.** This is why the comparison report puts raw
   and processed side by side rather than in a table.
3. **The decision has to come from measurement, not from a rule per case.**
   Writing a rule for each situation just moves the guesswork into code.

## What is already measurable

Tilt — how much of a scan's height variation a single plane accounts for —
is computed and reliable. On the six test scans it read 81%, 37%, 26%, 59%,
0%, 0%, and the two zeros were exactly the two the instrument had already
levelled. That number alone answers "does this scan need levelling at all",
which was previously guessed.

The same approach — measure first, decide from the measurement — is what the
artifact detection is for. See
[instrument-may-have-processed-it-already](instrument-may-have-processed-it-already.md).
