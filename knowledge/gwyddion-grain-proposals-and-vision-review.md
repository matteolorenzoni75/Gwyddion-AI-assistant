---
title: Gwyddion should propose masks; vision should judge their meaning
tags: [gwyddion, masking, grains, watershed, vision, training]
verified: 2026-09-16
confidence: documented-and-smoke-tested
---

# Gwyddion should propose masks; vision should judge their meaning

A global height threshold is only one grain marker.  Gwyddion 2.70 exposes
independent marking routes: height, slope and curvature thresholds; Otsu;
difference-of-Gaussians edge detection; and watershed.  It also has grain
filtering by properties and a logistic-regression grain marker, although the
latter is interactive and needs labelled examples before it can be automated.

Sources: [Gwyddion Grain Analysis](https://gwyddion.net/documentation/user-guide-en/grain-analysis.html),
[Gwyddion module list](https://gwyddion.net/module-list.en.php), and the
[grain-processing API](https://gwyddion.net/documentation/head/libgwyprocess/libgwyprocess-grains.php).

## Decision

Do **not** ask a vision model to draw a mask pixel-by-pixel before using what
the SPM software already knows.  Instead:

1. generate independent Gwyddion candidates on immutable copies of the map;
2. show height plus each cyan candidate overlay to the operator or vision
   model;
3. let it select, combine, reject, or request manual editing of a candidate;
4. validate the selected mask numerically before a background fit: enough
   unmasked area, per-row support, no increased slow-axis belly, and no
   unexplained loss of roughness.

The AI adds semantic judgement: it can see that a boundary follows a particle,
a terrace, a fibre, a feedback tail or ordinary texture.  The numerical guard
prevents a visually plausible selection from becoming an unsafe correction.

## What the first smoke test showed

On one blind corpus scan containing compact raised features, seven available
methods produced very different candidates: conservative height 1.5% of the
frame, inclusive height 4.1%, slope 1.2%, curvature 87.9%, edge 21.2% in
thousands of tiny regions, Otsu 4.2%, and watershed 31.9%.  This is evidence
that no single method can be silently preferred.  It is *not* a batch-wide
threshold calibration.

## Training evidence

The project’s own operator masks are the primary supervision because they
encode this instrument, these tip states and the actual scientific question.
Raw/processed pairs without masks are weak supervision only: many different
masks and operations can lead to a similar final image.

Useful external resources are complementary, not ground truth for this lab:

- [AFMDB](https://data-collections.psdi.ac.uk/communities/afmdb/about)
  collects raw AFM files with processed outputs and is explicitly intended to
  support deep-learning development;
- [AFMap-UNet data](https://zenodo.org/records/19373203) provides AFM
  segmentation examples, but its nuclear-imaging domain is unlike particle or
  terrace topography;
- [Ganesan et al.](https://arxiv.org/abs/2409.11438) found transform-based
  workflows stronger than ResNet50 for their AFM polymer-domain task, which
  supports retaining the measured descriptors alongside vision review;
- the [AFM ML review](https://www.frontiersin.org/journals/physics/articles/10.3389/fphy.2024.1347648/full)
  maps the broader AFM use cases but does not provide a universal segmentation
  label set.

Therefore external data may pretrain generic visual notions, but acceptance
thresholds and final evaluation must remain on held-out local operator masks.
