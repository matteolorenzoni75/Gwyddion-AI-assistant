---
title: What the tool is for
tags: [charter, scope, priorities, batch, quality, layout, interactive]
verified: 2026-09-03
confidence: stated-by-user
---

The user's own statement of the goal, given on 2026-09-03 and superseding any
inference from individual tasks. Read this before deciding what to build next,
and before deciding how hard to chase a defect.

## The objective, in their words

> In poche parole, il tool prende un batch (un giorno o un mese di misure) le
> rende fruibili e garantite, se sono fallate o non di qualità le scarta, come
> farebbe un operatore umano.

A batch in, a batch out: usable, vouched for, with the bad ones removed. The
benchmark is **a competent human operator**, not a perfect instrument.

## The five things it does

1. **Robust pattern recognition — explicitly *not* perfect.** Good enough to
   sort and route the work. See the correction below.
2. **Cleaning: noise and drift out.**
3. **Correcting the usual SPM measurement artifacts** — the ones that recur, not
   every conceivable one.
4. **Optimising the final layout of the topography**: better visibility, and
   contrast pushed onto the parts that matter. This is a deliverable in its own
   right, not a cosmetic afterthought — the image is what leaves the lab.
5. **Automating the routine and frequent measurements**, film thickness and
   roughness first.

## And a second, interactive mode

Through prompts, ad-hoc corrections and analyses that use Gwyddion's full
capability **without the user having to be a Gwyddion expert**. The LLM also
suggests: not only executing what is asked, but proposing what is worth doing.

This is the same split as [[two-routes-for-every-judgement]] seen from the
user's side — the batch route runs unattended, the interactive route is where
judgement is bought back in.

## The correction that came with it

> non ti fissare sul singolo dato che non torna

Said after two long detours: a 12% pitch discrepancy on one DVD scan, and a
one-by-one hunt through 31 images. Both produced real findings, and both cost
more than the finding was worth.

**How to apply.** Ask what a defect changes for a batch of a hundred scans
before spending on it. A measurement that is right on most images and says "I
don't know" on the rest is finished; one that is right on all of them is a
research project. Chase the single outlier only when it reveals something
systematic — the DVD did, in the end, because it measured the scanner rather
than the sample ([[lateral-distances-need-two-corrections]]) — and stop once it
has.

The order to work in follows from the objective: **make the batch path work end
to end first**, at whatever accuracy it currently has, then improve the weakest
step. A perfect periodicity measurement inside a pipeline that cannot yet
discard a bad scan or lay out a final image helps nobody.

## Related

[[a-wrong-label-costs-more-than-no-label]] is the same instinct applied to
recognition: robust means willing to abstain. Discarding a poor scan and
labelling one "varie" are the same act.
