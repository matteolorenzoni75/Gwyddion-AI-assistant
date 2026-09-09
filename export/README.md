# The corpus

56 real scans, converted to `.gwy`, with what this code currently says about
each of them. Enough to work on recognition and measurement without Gwyddion
installed — which is 205 of the 207 tests.

```
scans/scan-001.gwy … scan-056.gwy    as converted from the instrument
clean/scan-0NN.gwy                   the same 44 after cleaning
baseline.json
```

Both are here on purpose. `scans/` is what the instrument produced, and it is
what the quality checks, the cropping and the mask are judged on — it also
still holds every channel, so the phase maps are in there. `clean/` is what
the readings were computed from, and cleaning needs Gwyddion: shipping only
the converted files made the baseline impossible to reproduce for exactly the
people it was written for.

Twelve scans have no cleaned version, and that is not a gap — they were not
kept, or they are not height channels at all.

## The names are ids, and that is the point

The corpus is **blind**. Nothing may infer what a scan contains from what it is
called, and here there is nothing to infer it from. This is not only a privacy
measure: it is the project's oldest rule, and neutral ids make it true by
construction rather than by discipline.

It also means a filename can never be a shortcut. When a measurement and a
name agree in the full dataset, that agreement is evidence precisely because
nothing read the name to produce it.

Getting there took more than renaming the files. A scan carries its identity in
three places, and each was found only by looking for it: `/filename` holds the
full original path — in all 56 — `/N/log` is Gwyddion's processing log, and
`/N/meta/BaseName` is the Asylum metadata holding the sample's own name. All
three are stripped by `tools/make_export_corpus.py`. The height data is
untouched and verified identical to the source.

What remains in `/N/meta` is the instrument describing itself: scan rate, image
mode, set point, servo gains, line direction. That identifies nobody and is
what a future multichannel or drift correction will need.

## What is in it

Every family the code recognises, four of each — terraces, patterns, particle
layers, objects on a background, pits, uniform surfaces, and the ones no family
claims. Then every *verdict*, because an agent that never sees a rejected scan
cannot tell whether it would reject the right things:

- interrupted scans, cropped to the part that has data
- repeats of the same area
- one scan set aside as not worth using
- eight channels that are not height at all (phase maps) — `load_height`
  raises on these **by design**, and reading them is an open task
- scans where the cleaning took more roughness than the background accounts for
- a saturated scan, where the scanner ran out of travel

And the scans the `knowledge/` notes argue about by name, so the evidence behind
a decision cannot be quietly dropped by a selection rule.

## baseline.json is a net, not a truth

For each scan: the verdict, the recipe chosen, the measurements, the family and
the readings. **This is what the code says today, not what is correct.** Some of
it is certainly wrong — the open questions in `AGENTS.md` say where to look.

Use it as a regression net. Before touching anything, and again after:

```bash
python tools/diff_export_baseline.py
```

It recomputes every reading and prints only what moved; exit code 0 means
nothing did. That is a statement of fact, not a verdict — a difference can be
the improvement you were aiming for. Read it before accepting it. A change that
moves nothing has not been tested, and saying so is better than claiming it
works.

It found its own first bug: the baseline had no `tip_radius_nm`, so the tip
correction was silently skipped on recomputation and two particle sizes came
out different. The net paying for itself on its first run is the argument for
having one.

Regenerating the baseline itself needs a completed batch run
(`tools/make_export_corpus.py --run …`), so that part needs Gwyddion. The diff
does not.

## What you cannot do with this

Import raw instrument files, or run the cleaning recipes — both are Gwyddion,
through the Python 2.7 bridge. These files are already converted, so everything
downstream of that is open to you.
