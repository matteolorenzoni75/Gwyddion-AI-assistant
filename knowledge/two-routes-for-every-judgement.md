---
title: Two routes for every judgement, deterministic and learned
tags: [architecture, recognition, layout, reporting, design-rule]
verified: 2026-09-03
confidence: stated-by-user
---

User's instruction: *"il riconoscimento e l'ottimizzazione del layout (immagine
finale) sono sia deterministici sia AI recognition."*

Both of the places where the software has to *judge* something get **two
independent routes**, not one:

1. **Recognition** — what is on this surface.
2. **Layout of the final image** — how the exported picture is composed: colour
   range, scale bar, zoom, crop, DPI, and whether a shared scale across a batch
   helps or destroys the contrast.

## Why two, and not the better one

They fail differently, and that is the whole point.

The deterministic route is measurable, repeatable, and can be wrong in the same
way forever without noticing — the periodicity measurement returned the
two-pixel limit on every periodic scan in the pool and never once complained.
The learned route notices things nobody wrote a rule for, and is confidently
wrong on the cases it has not seen, which on a 55-scan pool is most of them.

Run both and the disagreement becomes the signal. Where they agree, the answer
is worth trusting and needs no attention. Where they disagree, that is exactly
the scan a person should look at — which is also what keeps the human cost flat
as the dataset grows from 55 scans to 13 GB.

## What this rules out

- **A rule engine alone.** It cannot say "this looks wrong" about something it
  was not told to check.
- **A model alone.** It cannot state *why*, and [[a-wrong-label-costs-more-than-no-label]]
  makes an unexplained confident label the most expensive output we can produce.
- **Silently choosing one route when the other is unavailable.** If only one
  ran, the output says so.

## For layout specifically

The deterministic side is arithmetic: colour range from percentiles, scale bar
sized to a round number of the scan width, DPI fixed, z-range grouped when a
batch spans more than about a decade — [[six-scans-were-filed-twice]] and the
50-scan export showed a factor 900 between z ranges, where one shared scale
made every image unreadable.

The learned side judges what arithmetic cannot: whether the picture *reads*.
Is the feature the person cares about visible at this zoom, is the bar sitting
on top of something, does this crop show the sample or the empty half of an
interrupted scan.

## Channels

Height only for now, at the user's instruction. **Error and phase come later,
for dynamic AFM** — the multichannel case is planned, not forgotten, and the
recognition side should be built so that adding a channel is adding an input,
not rewriting the judgement.
