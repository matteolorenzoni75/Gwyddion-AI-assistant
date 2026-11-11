# AFM Copilot — large local AFM backtest: taxonomy and safe pipeline (draft v1)

Status: **design only**. No batch processing is authorized by this specification.
The intended future source is `C:\AFM_Automation\All AFM Data`, recursively
including subdirectories, potentially a very large collection of AFM files.
It stays entirely on the user's Windows PC. Raw files, scan names, sample
metadata and local manifests must never be uploaded or committed.

## Fixed priorities

1. Preserve metrological fidelity of topography: correct physical X/Y/Z
   scales and units and retain raw original height values.
2. Diagnose acquisition errors independently from real sample morphology.
3. Apply minimal, defensible, reversible cleaning and levelling.
4. Measure, segment and recognize features **after** safe cleaning.
5. Collect anonymous aggregate backtest outcomes for improving the system.

A cleaning algorithm MUST NOT infer that any unusual geometric feature is
an artifact merely because the morphology model dislikes it. Classifier
predictions are suggestions, not cleaning instructions.

## A — data and channel identification

- Recursive, streaming inventory; avoid loading the full archive into memory.
- Read original files only. No writes within the source tree, including
  Gwyddion conversions, caches, temporary files, or result directories.
- Record paths, content hashes and acquisition metadata only in a private
  on-disk manifest outside both the source tree and Git checkout.
- Deduplicate by byte digest; compare *calibrated height matrices* and
  acquisition metadata before treating different formats as equivalent.
- Keep true trace/retrace channels separately, linked under one acquisition
  identity. Never split correlated channels across training and test.
- Reject fabricated calibration: missing / contradictory / ambiguous XYZ
  units or dimensions -> `needs_review`, not guessed values.
- Distinguish multiple channels: height/topography, amplitude, phase, current,
  potential, etc. Do not apply height-specific treatment to electrical maps.

## B — morphology (multi-attribute, do not relabel the 244-image corpus)

Retain the existing nine primary morphology families and their historical
expert labels: `fibres`, `flat_smooth`, `granular_continuous`,
`isolated_objects`, `mixed`, `periodic`, `pores`,
`rough_irregular`, `terraces`.

New *optional* multi-label descriptive attributes, not new exclusive classes:
- object polarity: raised, recessed, bidirectional, unknown;
- spatial arrangement: isolated, clustered, continuous, ordered, random;
- geometry: rounded, elongated, faceted, branched, network, unknown;
- spatial scale: feature size and spacing in physical units; no arbitrary
  pixel-only sizes masquerading as nm;
- background observability: clear substrate, partial, none;
- structural overlap: particles-on-film, steps-plus-islands, fibres-plus-grains.

`mixed` should be interpreted as multi-morphology, not as a substitute
for the acquisition-defect field. `rough_irregular` remains in the
reference database even when excluded from provisional 8-class fitting.

## C — acquisition and measurement errors

| Code | Evidence required | Allowed automated handling | Hold / veto |
|---|---|---|---|
| tilt | plane-fit gradient, robust background evidence | plane levelling | tall structures bias fit -> use mask/hold |
| bow | smooth low-frequency scanner curvature | low-order background only if supported | structural curvature / roughness loss |
| row_offset | isolated scan-line offsets | validated median-of-differences | line medians represent real sample |
| line_scar | locally discontinuous line segment | repair restricted to verified damaged pixels | true step / narrow ridge |
| spikes | isolated inconsistent outlier pixels | proposal with explicit mask; conservative opt-in | real nanodots, protrusions |
| highfreq_noise | estimated noise vs true fine-scale texture | cautious optional denoising | changes PSD, Sq, fine features |
| drift | distortion along scan axes and trace/retrace evidence | flag, compare direction and channels | cannot reconstruct reliable geometry |
| feedback_lag | scan-axis asymmetry, channel disagreement | flag only initially | damaged feature geometry |
| intermittent_feedback | local oscillatory jitter/rattle | flag only initially | true rough terraces |
| doubled_tip | repeated offset copies of features | flag for instrument review | avoid false deconvolution |
| saturation | clipping plateaus at hardware limits | flag, possibly exclude measurement | no invented values |
| periodic_interference | direction, scan rate and temporal frequency | flag; filter only with validated isolation | true sample periodicity |
| invalid_calibration | impossible/inconsistent units or extents | stop processing | never guess scale |

The existing `afm_copilot/quality.py` and `decide.py` already provide
some detectors, but their thresholds and false-positive behavior must be
reassessed before new default automation.

## D — correction policy and rescaling

Decision states: `safe_auto`, `conditional`, `propose_only`,
`no_reconstruction`. Default to conservative, record the reasons.

- Height value scaling (calibration) != changing height zero != changing
  displayed colour range != pixel resampling.
- Convert SI units only where source calibration is verified.
- Keep one unmodified reference image and a separate processed derivative;
  keep an operation log and masks for provenance.
- Compare before/after with physical metrics: retained step heights,
  roughness Sa/Sq, PSD / correlation length, feature count and geometry,
  masked area, fitting residual, scan-direction profile, trace/retrace
  agreement when available, number and fraction of interpolated pixels.
- Before/after gates must be morphology-aware: reducing global RMS can
  mean deleting *real* sample structure; high visual smoothness is not a
  sufficient success criterion.
- Abort/review if the fitting baseline is not identifiable, too many pixels
  would be synthesized, physical scale is unreliable, or protected structures
  change beyond established tolerances (to be calibrated, not invented).

Existing recipes in `afm_copilot/ops/recipes.py` include
`level-only`, `quick-clean`, `facet-terraces`,
`isolate-objects-flat`, `isolate-objects`, `roughness-ready`
and `despike`. Their catalog warnings are operational constraints, not
permission to run destructive operations on all images.

## E — feature recognition: last stage

- Recognize surfaces and features from physically scaled, minimally
  corrected data; preserve pre-correction evidence for cross-checking.
- Candidate labels are suggestions with calibrated confidence and abstention.
- Numerical measurements require defined valid mask / no fabricated pixels.
- Existing 244 expert labels remain unchanged. 233 exact-dedup candidate
  records formed the first local exploratory dataset; first 8-class
  ExtraTrees baseline used 231 records and reported OOF macro-F1 0.6203,
  accuracy 0.6147. **These are not independent-test scores.**
- New huge archive may be evaluated without up-front manual labeling by
  producing QA metrics, coverage, drift, warnings and image panels; it
  cannot yield a certified supervised accuracy without post-hoc ground truth.

## F — planned local-only backtest execution

Phase 0: preflight only: count formats/files, check permissions, disk,
units and duplicate patterns, dry-run sample; do not transform.
Phase 1: stratified exploratory subset across instruments and image quality,
with private records and aggregate failure rates.
Phase 2: conservative processing with reproducible recipe versions,
checkpoints and memory/CPU bounds. Allow stop/resume.
Phase 3: human review of *selected difficult failures*, not forced bulk
labeling; no automated training on pseudo-labels.
Phase 4: only after quality gates pass, expand to all files.

Safe outputs: aggregate counts by diagnostic outcome, format and operation
(where privacy-safe), no path/hash/note/sample-ID disclosures. Original
file paths, per-scan metadata and image previews remain private.

## Open engineering work BEFORE any full archive run

- Add channel-aware metadata ingestion and calibrated matrix signatures for
  cross-format dedup; verify real trace/retrace pairs by channels.
- Build defect diagnosis + correction-veto audit independently of morphology.
- Add quantitative before/after acceptance metrics and reversible outputs.
- Add streaming inventory, checkpoints, resource budgets, failure isolation,
  and isolated per-scan Gwyddion conversion workdirs.
- Add a diagnostic review UI for disputed *artifact versus true feature*.
- Produce a local dry-run summary before enabling any batch write of
  derivative files.

This document **does not** change current automatic recipe selection.
