---
title: What the operator must be asked, and what may be decided
tags: [decisions, autonomy, despike, repair, objects, user-rules]
verified: 2026-09-07
confidence: stated-by-user
---

The user drew this line twice in one session, once about spikes and once about
dirt:

> la decisione di rimuovere (piallare) dei corpuscoli va chiesta all'operatore
> altrimenti rischiamo di piallare delle nanoparticelle

**Anything that removes or flattens an object is a proposal, never a default.**
Nothing in an image distinguishes a speck of dirt from a particle that is the
point of the experiment. That is a fact about the sample, and the software does
not have it.

## Decided automatically

Corrections that remove what the *instrument* added, where the surface
underneath is untouched:

- levelling, background removal, row alignment
- scar and stroke repair — a stroke along the fast axis is the tip losing and
  regaining the surface, never the sample
- cropping a frame that stopped early
- setting a zero

And one refusal, because there is genuinely nothing to work with: a frame that
never filled.

## Proposed, with the evidence, and applied only on a yes

Anything that erases or reshapes something that might be the sample:

- **despiking** — offered behind `--despike`. Ranked across 232 scans the
  highest scorers were nanoparticles on silicon, a lithographic pattern and a
  regular dot lattice, all small, sharp and real. No threshold separated those
  from dropouts, and repairing is not free: one scan lost 22% of its roughness
  to it.
- **erasing dirt and filling the hole** — Gwyddion's Remove Spots, and
  `mark_outliers` + `interpolate_under_mask` here.
- **lifting a dragged dish back to level** — `repair.lift_region`. Gentler than
  erasing, since the texture inside survives, but it still reshapes real
  measurements.

## And one that was wrong until corrected

**Noise is not grounds for discarding.** It used to be fatal on its own, and a
scan of HOPG went in the bin whose terraces were perfectly good — the user's
verdict: *"è veramente noisy. le terrazze sono già corrette, il problema è solo
il rumore, qui hai fallito."* Something that can be filtered is a reason to
filter, not to discard. See also
[[a-wrong-label-costs-more-than-no-label]]: throwing away good data is the
same error as mislabelling it, with a worse outcome.

## The test to apply to a new operation

Ask what it costs when it fires on a scan it should not have. Levelling a scan
that needed no levelling costs a little roughness and is visible in the
over-flattening check. Flattening a field of nanoparticles costs the
experiment, silently, and leaves an image that looks fine.
