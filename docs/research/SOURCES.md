# Sources

Key references behind [ARTIFACT_TAXONOMY.md](ARTIFACT_TAXONOMY.md),
[QUALITY_METRICS.md](QUALITY_METRICS.md) and [ECOSYSTEM.md](ECOSYSTEM.md).

Items marked ⚠️ were reachable only as an abstract, landing page or search
snippet (paywall, or a PDF that would not extract). Do not treat them as
settled.

---

## Must-read, in priority order

1. **Nečas & Klapetek et al., "How levelling and scan line corrections ruin
   roughness measurement and how to prevent it", Sci. Rep. 10, 15294 (2020)** —
   the quantitative bias framework. Open access.
   https://pmc.ncbi.nlm.nih.gov/articles/PMC7499267/ ·
   https://www.nature.com/articles/s41598-020-72171-8
2. **"Artifact Removal and Image Restoration in AFM: A Structured Mask-Guided
   Directional Inpainting Approach", arXiv:2602.04051** — classifier →
   segmentation → mask-aware "Smart Flatten"; the 2.7× residual improvement.
   https://arxiv.org/abs/2602.04051
3. **Li et al., "Stripe noise removal in conductive atomic force microscopy",
   Sci. Rep. 14 (2024)** — the 16-method benchmark; LRR wins at 90.43% SSIM.
   https://pmc.ncbi.nlm.nih.gov/articles/PMC10873331/
4. **AILA / AFMBench — "Evaluating large language model agents for automation of
   atomic force microscopy", Nat. Commun. 16 (2025)** ⚠️ (Nature paywalled;
   arXiv PDF would not extract). https://arxiv.org/abs/2501.10385 ·
   https://www.nature.com/articles/s41467-025-64105-7
5. **Villarrubia, "Algorithms for Scanned Probe Microscope Image Simulation,
   Surface Reconstruction, and Tip Estimation", J. Res. NIST 102, 425 (1997)** —
   the foundation of blind tip reconstruction. Open access.
   https://pubmed.ncbi.nlm.nih.gov/27805154/
6. **Omega, Nat. Methods 21 (2024)** — LLM agent inside an image-analysis
   application; the closest architectural prior art.
   https://www.nature.com/articles/s41592-024-02310-w ·
   https://github.com/royerlab/napari-chatgpt

---

## Artifact taxonomy

- Ricci & Braga, "Recognizing and Avoiding Artifacts in AFM Imaging",
  Methods Mol Biol 242:25 (2004) ⚠️ — the five-source framing.
  https://pubmed.ncbi.nlm.nih.gov/14578511/
- Golek et al., "AFM image artifacts", Appl. Surf. Sci. 304, 11 (2014) ⚠️
  https://www.sciencedirect.com/science/article/abs/pii/S0169433214002013
- Eaton & West, AFM Artifacts FAQ (open, well illustrated)
  https://www.fc.up.pt/pessoas/peter.eaton/artifacts/artifacts.html
- Bruker SPM Training Guide — AFM Image Quality (the most operationally specific
  single page found; source of the 2nd/3rd-order bow distinction, the 1.5–2.5 μm
  optical interference period, and the 0.3–1 Å noise figure)
  https://www.nanophys.kth.se/nanolab/afm/icon/bruker-help/Content/SPM%20Training%20Guide/Atomic%20Force%20Microscopy%20(AFM)/AFM%20Image%20Quality.htm
- DoITPoMS Cambridge — scanner-related and feedback-related artefacts ⚠️
  https://www.doitpoms.ac.uk/tlplib/afm/scanner_related.php
- Scanning probe microscopy, Nat. Rev. Methods Primers 1, 35 (2021)
  https://www.nature.com/articles/s43586-021-00037-y

### Drift, creep, hysteresis
- unDrift, Beilstein J. Nanotechnol. 14, 101 (2023) — three drift algorithms,
  ±25 pm / ±2°, reads `.gwy` natively.
  https://www.beilstein-journals.org/bjnano/articles/14/101
- DHCT joint drift/hysteresis/creep transform, Rev. Sci. Instrum. 88, 013708
  (2017). https://pubs.aip.org/aip/rsi/article/88/1/013708/367717/
- Vertical drift correction and "illusory slope" elimination
  https://www.cambridge.org/core/journals/microscopy-and-microanalysis/article/6C2E9EDC1ADF5F53C87F5EBF8DC95098

### Tip artifacts
- Differentiable blind tip reconstruction, Sci. Rep. (2023) — the Julia
  implementation. https://www.nature.com/articles/s41598-022-27057-2
- Canet-Ferrer et al., Nanotechnology 25, 395703 (2014) — quantitative
  broadening/deconvolution for nanoparticles.
  https://iopscience.iop.org/article/10.1088/0957-4484/25/39/395703
- NIST, blind estimation of general tip shape
  https://www.nist.gov/publications/blind-estimation-general-tip-shape-afm-imaging

### Step height metrology
- ISO 5436 step-height definition ⚠️
  https://www.researchgate.net/figure/The-definition-of-the-step-height-according-to-ISO-5436_fig4_267641264
- NIST traceable pm-level step height metrology
  https://www.nist.gov/publications/traceable-pico-meter-level-step-height-metrology

---

## Detection methods

- **DeStripe**, BMC Struct. Biol. 11:7 (2011) — heterogeneity function
  (Laplacian of log spectrum + magnitude), automatic thresholding, and the
  non-negative-noise physical constraint. Evaluated by visual inspection only.
  https://pmc.ncbi.nlm.nih.gov/articles/PMC3749244/
- Oblique stripe removal via oriented variation, arXiv:1809.02043 — automatic
  stripe-direction detection at arbitrary angles (remote sensing).
  https://arxiv.org/abs/1809.02043
- Radon and Hough, a unifying perspective, arXiv:1605.09201
  https://arxiv.org/abs/1605.09201
- Segmentation-free Radon orientation + size detection in microscopy
  https://pmc.ncbi.nlm.nih.gov/articles/PMC12322599/
- Adaptive Gaussian notch filter, IET Image Process. (2020)
  https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/iet-ipr.2018.5707
- PSD measurement — "Nanoscale measurement of the PSD of surface roughness: how
  to solve a difficult experimental challenge" (also a feedback-artifact
  detector). https://pmc.ncbi.nlm.nih.gov/articles/PMC3380722/
- Quantitative AFM: statistical treatment of HS-AFM data for QC,
  Ultramicroscopy (2022) ⚠️ — Ssk/Sku/Rz/Sz as automatic anomaly flags over
  >200 images. https://pubmed.ncbi.nlm.nih.gov/35598347/

## Machine learning in SPM

- Biswas et al., "Conversational LLM-Based Decision Support for Defect
  Classification in AFM Images", IEEE OJIM (2025) — 91.4% accuracy; 93% recall
  tip contamination, 60% not-tracking. https://ieeexplore.ieee.org/document/11096088/
- Kocur et al., Ultramicroscopy 246, 113666 (2023) — ResU-Net trained purely on
  synthetic data, exploits trace/retrace; **public generator, model and an
  82-scan evaluation dataset**. https://pubmed.ncbi.nlm.nih.gov/36599269/ ·
  https://www.nenovision.com/resources/articles/correction-of-afm-data-artifacts-using-a-convolutional-neural-network
- DeepSPM, Commun. Phys. 3, 54 (2020) — CNN image-quality assessment + deep-RL
  tip conditioning. https://www.nature.com/articles/s42005-020-0317-3
- Rashidi & Wolkow, ACS Nano 12, 5185 (2018) — 97% / >99% tip-state
  classification. https://pubs.acs.org/doi/abs/10.1021/acsnano.8b02208
- "Automated Scanning Probe Tip State Classification without Machine Learning",
  ACS Nano 18, 2384 (2024) — the counterpoint: classical descriptors match CNNs.
  https://pubs.acs.org/doi/full/10.1021/acsnano.3c10597
- CNNs in SPM: a review, Beilstein J. Nanotechnol. 12, 878 (2021). Open access.
  https://www.beilstein-journals.org/bjnano/articles/12/66
- SimuScan, Nat. Commun. (2026) ⚠️ — synthetic AFM images with realistic
  artifacts. https://www.nature.com/articles/s41467-026-70421-3

## LLM agents at instruments

- "Leveraging Large Language Models and Social Media for Automation in Scanning
  Probe Microscopy", arXiv:2405.15490 — real UHV STM control; **no automated
  image interpretation** (a human judged the results).
  https://arxiv.org/html/2405.15490
- "It's not the Language Model, it's the Tool: Deterministic Mediation for
  Scientific Workflows", arXiv:2605.13245 https://arxiv.org/pdf/2605.13245
- Explainability and human intervention in autonomous SPM, arXiv:2302.06577 —
  humans make high-level slow decisions, algorithms make low-level fast ones.
  https://arxiv.org/abs/2302.06577
- IQAGPT, arXiv:2312.15663 — a fine-tuned captioning vision model + LLM beat
  both GPT-4 and CLIP-IQA at image quality assessment.
  https://arxiv.org/abs/2312.15663
- BioImage.IO Chatbot, Nat. Methods 21 (2024)
  https://www.nature.com/articles/s41592-024-02370-y

## Gwyddion documentation

- User guide index https://gwyddion.net/documentation/user-guide-en/
- Scan line artefacts (Align Rows methods, Mark Scars parameters)
  https://gwyddion.net/documentation/user-guide-en/scan-line-defects.html
- Levelling and background
  https://gwyddion.net/documentation/user-guide-en/leveling-and-background.html
- Tip convolution artefacts
  https://gwyddion.net/documentation/user-guide-en/tip-convolution-artefacts.html
- Synthetic surfaces (the training-data generators)
  https://gwyddion.net/documentation/user-guide-en/synthetic.html
- Statistical analysis (PSDF, ACF, HHCF)
  https://gwyddion.net/documentation/user-guide-en/statistical-analysis.html
- pygwy API reference http://gwyddion.net/documentation/head/pygwy/
- Module list https://gwyddion.net/module-list-nocss.en.php
- Project news (Gwyddion 3 status) https://gwyddion.net/project-news.php

## Python ecosystem

- `gwyfile` (MIT, reads **and writes** .gwy) https://github.com/tuxu/gwyfile
- `igor2` (LGPL-3, .ibw) https://github.com/AFM-analysis/igor2
- `AFMReader` (Asylum .ibw glue) https://github.com/AFM-SPM/AFMReader
- `TopoStats` (GPL-3; see its `legacy` branch `pygwytracing.py`)
  https://github.com/AFM-SPM/TopoStats
- `SPIEPy` (BSD-2; `flatten_by_iterate_mask`)
  https://webspace.science.uu.nl/~zeven101/SPIEPy/
- `pySPM` (Apache-2.0) https://github.com/scholi/pySPM
- `pystripe` (MIT, wavelet-FFT destriping)
  https://github.com/chunglabmit/pystripe
- `gsffile` (MIT, Gwyddion Simple Field)
  https://github.com/angelo-peronio/gsffile
- `onakanob/PyGwyBatch` (MIT, minimal Py3→Py2 bridge)
  https://github.com/onakanob/PyGwyBatch
- SciFiReaders — ships an MCP server; the best available template
  https://github.com/pycroscopy/SciFiReaders
