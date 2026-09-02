---
title: A wrong label costs more than no label
tags: [recognition, reporting, confidence, user-rules]
verified: 2026-09-02
confidence: stated-by-user
---

User's instruction, given while labelling the test pool: *"non devi accanirti
per forza nel riconoscimento, l'importante è non fare errori."*

Do not strain to produce a classification. Recognising nothing is an acceptable
outcome; recognising something wrongly is not.

## Why it costs more

The person reading the output is deciding what to do with a sample. "I don't
recognise this" leaves them exactly where they were and they look themselves.
"This is a porous film" when it is not sends them down a path, and the
confidence of the statement is what makes them follow it. The error is not the
wrong word — it is the unearned certainty attached to it.

There is a version of this that is specific to AFM: **calling something an
artifact when it is morphology.** It happened on `Camilla sample - detail 01`,
where paired light-and-dark streaks near one edge were called a tip artifact
and the user corrected it — *"l'immagine è buona, pura morfologia del
campione"*. That mistake is worse than most, because the suggested remedy is to
remove or filter the feature. Deleting real data is a harder error to undo than
failing to name it.

## How to apply

- Say what is *measured* without hedging: sizes, counts, RMS, period, angle.
  Those are numbers and they stand on their own.
- Say what is *inferred* separately, and only when the evidence in the image
  supports it. When it does not, say nothing rather than something.
- Never call a feature an artifact unless there is a positive reason —
  a repeat at the scan-line frequency, a shape that repeats identically across
  unrelated objects, a discontinuity that follows the fast scan axis. "It looks
  odd" is not a reason.
- A "varie" bucket is a real answer. See [[fixed-recipes-cannot-decide]]: the
  same discipline that stops a recipe being chosen by eye stops a label being
  chosen by eye.
