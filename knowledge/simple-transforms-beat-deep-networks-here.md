---
title: On AFM images, simple transforms beat deep networks
tags: [recognition, machine-learning, references, periodicity, fourier]
verified: 2026-09-02
confidence: observed
---

Three independent results, all on scanning-probe data, all finding that
classical measurements outperform deep networks. Recorded because they set the
direction for the recognition work and because the instinct in 2026 is to reach
for a network first.

## The measurements

**Ganesan et al., "Machine learning for analyzing atomic force microscopy
images generated from polymer blends", *Digital Discovery* 3:2533 (2024).**
https://pubs.rsc.org/dd/article/3/12/2533/846130/ · preprint
https://arxiv.org/pdf/2409.11438

They compared feature extractors on real AFM images: discrete Fourier
transform, discrete cosine transform, wavelet, Radon transform, and ResNet50.
The transforms won. In their words, the DFT/DCT workflow "works the best" and
"the popular ResNet50 deep learning approach from computer vision exhibited
relatively poorer performance".

A second finding from the same work, worth as much as the first: of mean,
variance, skewness and kurtosis computed per tile, **variance carried the
information**. They measured the correlations and found skewness and kurtosis
almost perfectly correlated with each other and with the mean, while variance
was independent of all three. Three of the four descriptors were the same
descriptor wearing different clothes.

Caveat stated honestly: their task was segmenting domains *within* one image,
not classifying whole images, and their ResNet50 was handicapped by a tile size
below its minimum input. The result is direct evidence, not proof.

**Gordon et al., "Automated Scanning Probe Tip State Classification without
Machine Learning", *ACS Nano* 18:2384 (2024).**
https://pmc.ncbi.nlm.nih.gov/articles/PMC10811750/

Title says it. They matched CNN performance on tip-state classification using
normalised cross-correlation against an ideal-tip template plus a circularity
measure — the standard deviation of the radius across rotations, thresholded.

**Sokolov, "On machine learning analysis of atomic force microscopy images for
image classification, sample surface recognition", *PCCP* 26:11263 (2024).**
https://pubs.rsc.org/en/content/articlelanding/2024/cp/d3cp05673b ·
https://arxiv.org/abs/2403.16230

Written for exactly this situation: AFM classification from a small database,
deliberately avoiding CNNs. Reaches 94% on a hard two-class problem using
35–40 surface parameters, pruned by cross-correlation, ranked by importance,
down to about ten, then a non-deep classifier.

Two things from it to use directly:

- **The rule of ten.** At least ten examples per feature used. With 55 real
  scans that supports about five features — which is why the pool is a test
  set, not a training set.
- **The label-randomisation control.** Reassign the class labels at random and
  rerun the whole pipeline. Whatever it still scores above chance is the
  overfitting, measured rather than assumed. One extra loop, and the best
  defence available against fooling ourselves on a small set.

He also warns off phase and error-signal channels as instrument-dependent and
poorly repeatable, and recommends channels in absolute units. Height only, as
here, is the right choice.

## The decision taken

**Both methods, not one.** Periodic structure is checked by transform — the
Fourier route already implemented, which finds stripes at any angle and gives
their spacing — and the surface descriptors run alongside it. Neither replaces
the other: the transform answers "is this repeating, how, and which way", the
descriptors answer "what kind of surface is this". A network, if it ever
arrives, comes after both and has to beat them.
