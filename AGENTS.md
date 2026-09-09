# Working on AFM Copilot

Instructions for a coding agent picking this project up. Read this before
changing anything; read `README.md` for what the project *is*.

## What the tool is for

The owner's words, and they are the specification:

> In poche parole, il tool prende un batch (un giorno o un mese di misure) le
> rende fruibili e garantite, se sono fallate o non di qualità le scarta, come
> farebbe un operatore umano.

A batch in, usable and vouched-for out. Five jobs: robust pattern recognition
(**explicitly not perfect**), cleaning noise and drift, correcting typical SPM
artifacts, laying out the final topography so the interesting part is visible,
and automating the routine measurements — film thickness, roughness, object
size.

## Start here

```bash
pip install -e ".[dev]"
python -m pytest tests -q
```

**205 of the 207 tests need nothing but Python 3.** Only two touch Gwyddion,
and they skip themselves when it is absent. Verified by pointing
`GWYDDION_ROOT` at a path that does not exist: `205 passed, 2 skipped`.

So on Linux, in a container, or anywhere without the Windows toolchain, you can
work on recognition, measurement, judgement, masking and layout — which is most
of the codebase — with the full suite green.

## What needs Gwyddion, and what does not

Gwyddion does exactly three things:

1. **Imports** instrument formats (Asylum `.ibw` and the rest) into `.gwy`
2. Runs the **reference algorithms**: level, polylevel, linematch, scars, grain
   marking, zero-fixing
3. Supplies its own automatic colour range, for the second version of each
   picture

Everything else is Python 3 and never touches it. `gwyfile` reads **and writes**
`.gwy` including the mask; `igor2` reads the Asylum scan note straight from the
original file. All judging, measuring, recognising, masking and page layout is
ours. Measured: the bridge costs 0.05 s per scan, the Python 3 side 1.15 s.

Practical consequence: with a folder of already-converted `.gwy` files you can
do nearly everything. Without one you cannot run `afm-copilot batch` end to end.

**`export/` is that folder.** 56 real scans covering every family and every
verdict, plus `baseline.json` — what this code says about each of them today,
to be used as a regression net and never as ground truth. Read
`export/README.md` first. The scans are named `scan-001` … `scan-056` on
purpose: the corpus is blind, and there is no name in it to read.

| | |
|---|---|
| Gwyddion 2.70 **32-bit** | `GWYDDION_ROOT`, default `C:\Program Files (x86)\Gwyddion` |
| Python 2.7 **32-bit** | `PYTHON27`, default `C:\Python27\python.exe` |

PyGwy exists **only** in the 32-bit build. There is no `--script` flag; the
bridge imports `bin/gwy.pyd` from a plain 2.7 interpreter. See `README.md`.

The full sample corpus (`C:\AFM_Automation\OLD input IMAGES`, 241 scans) is
**not in this repository** — it is 453 MB of raw instrument files, and their
filenames carry collaborators' names. A few tests reference it by absolute path
and skip without it. Work from `export/` instead.

## Rules that are not up for discussion

These come from the owner. They are not style preferences; each was paid for.

1. **A wrong label costs more than no label.**
   > non devi accanirti per forza nel riconoscimento, l'importante è non fare
   > errori

   A refusal is a result. `measure_film_thickness` returning `ok=False` with a
   reason is a *success*. Never overrule a refusal with a weaker test — that
   bug shipped once and printed "step 35.1 nm" directly under the routine's own
   words "there is no measurable step in this image".

2. **Never call morphology an artifact.** Real sample structure has been
   misdiagnosed as tip damage here. When unsure, say nothing.

3. **Anything that removes material is proposed, never applied.**
   > la decisione di rimuovere (piallare) dei corpuscoli va chiesta
   > all'operatore altrimenti rischiamo di piallare delle nanoparticelle

   `repair.py` exists to build proposals. Background corrections apply freely;
   object removal never does.

4. **Flat surfaces are the fixed point.**
   > le superfici regolari e terrazze piatte di solito sono un buon punto saldo

   Whatever a correction does, what arrived flat must leave flat. There is a
   regression check for this — see below.

5. **Don't chase the single outlier.**
   > non ti fissare sul singolo dato che non torna

   And: `prediligiamo l'efficienza, in generale non dobbiamo essere perfetti,
   ma molto bravi dove il riconoscimento è inequivocabile`.

6. **Small patches, never rewrites.** A refactor on the predecessor project
   replaced working code with stubs. Do not restructure working files.

7. **PyGwy scripts are Python 2.7.** `import gwy` at the top of a file means
   2.7: no f-strings, no `pathlib`, no type hints, no dataclasses, no walrus,
   no `exist_ok=` / `capture_output=`.

8. **The test corpus is blind.** Filenames are uninformative or deliberately
   wrong. Never infer content from a name. Where a filename *does* agree with a
   measurement, that is evidence precisely because nothing read it: a file
   whose name ends in `20nm005`, measuring 20.0 nm, is a free check.

## How to work here

**Measure before you tune.** Most bugs found in this codebase were found by
running a number across the whole batch, not by reasoning about one scan. When
tempted to adjust a threshold, first print the quantity for all 199 kept scans
and look at where the samples actually separate. Tuning on one scan with a
metric you do not trust is the recurring trap.

**Every correction needs a regression check that can fail.** The masked row
correction looked right and spoiled 30 of 79 scans; nobody would have noticed
without a measurement that could say so. Existing checks worth reusing:

- *belly along the slow axis*: collapse the frame to its mean profile down the
  image, remove a straight line, and look at what is left. It must not grow.
- *flatness within a level*: fit a plane to one level's pixels alone; the
  residual must not grow.
- *over-flattening*: how much roughness the cleaning removed against what the
  background can account for.

**Prefer chaining conclusions to re-deriving them.** Two separate bugs came
from a rule reading a raw signal where it should have read the previous rule's
verdict — `bimodality` is an input, "we could not find a step" is a result.
Rules that build on each other need far fewer thresholds.

**Constants carry their evidence.** Every threshold in `decide.py` and
`analysis.py` is next to a comment saying what was measured to choose it, often
with the table. Keep that up; a bare number is unmaintainable by the next agent.

**Do not minimise Sq.** Every levelling step biases roughness downward by a
calculable amount. An optimiser chasing low Sq destroys real morphology.

## Where things are

| | |
|---|---|
| `afm_copilot/decide.py` | what to do to a scan, and the masking |
| `afm_copilot/analysis.py` | measurements, and the families |
| `afm_copilot/quality.py` | the seven checks that judge a scan |
| `afm_copilot/frame.py` | interrupted scans, cropping |
| `afm_copilot/features.py` | objects, periodicity, roughness |
| `afm_copilot/tip.py` | probe radius, tip-convolution correction |
| `afm_copilot/render.py` | the guided colour scale |
| `afm_copilot/batch.py` | the end-to-end path |
| `afm_copilot/ops/` | the Gwyddion operation catalog and the recipes |
| `afm_copilot/bridge.py` | the Python 2.7 subprocess |
| `pygwy/` | the 2.7 scripts themselves |
| `knowledge/` | **31 notes: why things are the way they are** |
| `docs/` | the PyGwy API inventory, the channel survey, findings |

`knowledge/` is the important one. Each note states a finding, the measurement
behind it, and what was tried and abandoned. Before changing a detector, read
the note that covers it — several obvious ideas in here have already been
tested and are worse than what is there. `afm_copilot/knowledge.py` loads them;
notes need YAML front matter with `title`, `tags`, `verified`, `confidence`, and
`tests/test_knowledge.py` fails on a malformed one.

## What is open

- **Multichannel**: error and phase for dynamic AFM. Eight phase maps are
  already set aside by the batch, labelled "not height, kept for when we read
  them". Nothing reads them yet.
- **XY piezo lag** deforming scans (`ALEX_AS_*`), and drift/non-linearity
  correction generally. Gwyddion has functions for this; none are wired up.
- **Terraces missed**: the level detector finds 19 of 199. At least one scan
  with large flat domains is rejected and may be a real miss.
- **Unrouted code**: `repair.lift_region`, `repair.find_dishes`, and the
  `grow_mask` / `mark_raised_objects` / `drop_small_marks` operations exist and
  nothing calls them.
- **Tip wear detection** was attempted five ways and shipped nothing; every
  approach needed isolated objects on a clean background, which the flagged
  scans do not have. Read the knowledge notes before trying a sixth.
- **Despiking** is opt-in only (`--despike`): the highest-scoring candidates in
  the batch are real nanoparticles and a lithographic pattern.
