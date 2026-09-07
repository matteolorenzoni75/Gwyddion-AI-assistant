---
title: The default tip, and heights that will not settle
tags: [tip, probes, non-contact, bistability, quality, artifacts]
verified: 2026-09-07
confidence: stated-by-user
---

Two things the user asked for on the same day, both about the probe rather than
the sample.

## The tip we are using, when nothing tells us otherwise

Blind tip estimation belongs among the first steps — but **it cannot always be
recovered from the image**: it needs features sharper than the tip, and plenty
of scans have none. So there has to be a default, and here it is:

> **AC160** — the standard silicon pyramidal probe, ~300 kHz, nominal radius
> **10 nm**, or **up to 30 nm when coated**.

That is enough to run the tip correction from
[[the-tip-is-in-every-measurement]] with a stated assumption instead of no
correction at all: a 50 nm particle imaged with a 10 nm tip reads about 90 nm
wide by 4·√(R·r); with a 30 nm coated tip, about 155 nm. The difference between
those two numbers is why the assumption has to be stated wherever a width is
reported.

Order of preference: blind estimation from the scan; failing that a
characterisation scan from the same session; failing that the nominal radius
above, said out loud.

## Non-contact done badly: the height stops settling

> se le immagini sono acquisite in Non Contact ed il non contact non è eseguito
> bene, si può facilmente scivolare in una zona di bistabilità, tra regime
> repulsivo e attrattivo.

The tip ends up near the boundary between the attractive and the repulsive
regime and flips between them. The height record then rattles from pixel to
pixel — **and only where the interaction crosses that boundary**, so it lands
on the features while the flat background records nothing wrong. A global noise
measure is blind to it: on `noisy drops` the drop rattles by 9 nm while the
rest of the frame sits at 0.4, and the average of the two is unremarkable.

### What the check manages, measured

`quality._check_rattle` looks for height that departs from a straight line far
more than usual **and** alternates within a few pixels — an edge is one event, a
rattle is many. Against the user's labels:

| scan | area | contrast | typical jitter | truth |
| --- | --- | --- | --- | --- |
| `noisy drops` trace & retrace | 2.8% | 23× | 0.41 nm | bistable ✓ caught |
| `NPs coated SiO2 50 nm` 005/006 | 1.9% | — | — | bistable ✓ caught |
| `fibers 2` trace & retrace | 2.0% | 7× | 16.5 nm | bistable ✗ missed |
| `CdSe np DB` 2013/2014 | 6.9% | 18× | 0.39 nm | **morphology** ✗ flagged |

Four of six caught, 14 of 161 flagged. It misses `fibers 2` because that whole
frame jitters by 16 nm, so nothing stands out against it — the two true cases
are wildly unlike each other. And the one confirmed false positive scores
*higher* than a true one on both axes, so **no threshold separates them**.

That is why the wording reports the measurement and offers both readings rather
than naming the cause. The user had already corrected exactly this mistake once
in this project, on streaks that were real morphology, and
[[a-wrong-label-costs-more-than-no-label]] is the standing rule.

### One fix that came out of it and stands on its own

The checks now run on the **cropped** frame. A dead band is not a flat sample:
its edge reads as a step, its interior as saturation, and its border with the
live data rattles — so five of the nineteen scans first flagged were only
showing where the scan had stopped.

## The shape of both problems

Tip wear and bistability are both instantly obvious to look at and resist every
statistic tried so far — five attempts for one, four for the other. Both belong
on the learned side of [[two-routes-for-every-judgement]], with the
measurements supporting rather than deciding.
