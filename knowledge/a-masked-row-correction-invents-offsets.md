---
title: A masked row correction invents the offsets it cannot measure
tags: [masking, levelling, rows, gwyddion, artifacts]
verified: 2026-09-07
confidence: measured
---

# A masked row correction invents the offsets it cannot measure

The user's own manual result was a masked median of differences:

> mascherando l'oggetto a mano, sono riuscito poi a farlo...usando median of
> differences

Automating it made 30 scans worse. His mask was drawn tight around one object;
ours covers a third to a half of the frame, and that is a different operation
with the same name.

## How it shows

Collapse a frame to its mean profile down the slow axis and remove a straight
line. What is left is curvature -- a belly. Across the batch that belly **grew
on 30 of the 79 scans on the masked route**, by up to 156 nm, and on **none**
of the scans that never saw a mask.

Run one file through Gwyddion's three masking modes and it is not subtle:

    masking = 0 (exclude)     belly  43 nm
    masking = 1 (include)     belly 107 nm
    masking = 2 (no mask)     belly   0.34 nm

Both masked modes are bad, which rules out "we passed the wrong enum". The
cause is simpler: a line correction judges each row from its own background,
and where an object spans the whole row there is no background in it. That
row's offset is not measured, it is invented, and a run of invented offsets is
a belly.

## Why no threshold saves it

The obvious rule is "only mask when every row keeps enough background". It
does not work:

    worst row <= 40% masked    4 admitted, 1 still spoiled
    worst row <= 50% masked   11 admitted, 2 still spoiled
    worst row <= 60% masked   23 admitted, 8 still spoiled

One spoiled scan has a worst row of 23%. There is no cut that separates the 30
from the rest, so there is no honest way to run this automatically.

## What replaced it

The masked **background fit** stays -- that is the part that was asked for and
the part that works. The row correction runs after the mask is cleared, in its
ordinary unmasked form. That combination gives:

    scans gaining a belly       31  ->  1   (and that one is 1.5 nm)
    the worst case, 121127-005  150.67 nm -> 1.42 nm

Better than the masked version ever managed on that scan (42.71 nm). The
masked operation stays in the catalog, marked as needing a tight hand-drawn
mask, because with one it is the right tool.

See also: `what-the-operator-must-be-asked.md`,
`the-drag-belongs-to-the-object.md`.
