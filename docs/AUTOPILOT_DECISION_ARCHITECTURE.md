# AFM Copilot: mask-centric autonomous processing

Status: architecture decision and implementation requirements, NOT a shipped autonomous agent.
Date: 2026-11-11.

## Product decision

The operator supplies an AFM acquisition and a scientific objective. AFM Copilot must select masks, operations, parameters, ordering and stopping conditions itself, examine intermediate results and revise its plan when justified. A catalogue of recipes requiring manual selection is NOT the final product.

Recipes remain internal reusable tools and an expert fallback. The default interface should offer automatic analysis/correction, the proposed result, and acceptance/rejection or targeted intervention. Manual threshold adjustment is an override and a source of expert feedback, not a required step for every image.

Mask management is a first-class component, not a preliminary checkbox. Gwyddion remains the numerical executor. No language or image-generation model fabricates corrected height data.

## Present implementation versus target

The existing branch has deterministic diagnosis, operation/recipe catalogues, correction gates, an exploratory morphology classifier, manual threshold review, Gwyddion execution and comparison views. It does NOT yet have the closed-loop planner described here, a local VLM service or a remote model integration.

The current masked comparison path executes a fixed operator-approved masked fit, optionally followed by scar removal. It is a building block, not an autonomous processing policy. The morphology classifier alone is not a policy that knows which corrections to apply or when to rebuild a mask.

## 1. Acquisition state and evidence

Maintain an acquisition bundle with channel identity, direction, calibration provenance, coordinate frame, raw content identity and immutable source reference. Height is the primary processing signal; phase, amplitude, error, electrical and other channels retain their own units and may provide corroborating evidence only when association and registration are justified.

The planner receives numeric descriptors, physical units, line profiles, histograms, candidate masks, scan-direction evidence and calibrated image previews. It does not receive a misleading GUI screenshot as its only evidence. Image previews are representations, not the arrays used to calculate corrections.

A provisional background used to understand the scene is not automatically committed as a processing step. Preserve both raw and provisional evidence to avoid erasing broad features before identifying them.

## 2. Mask manager

Maintain separate semantic masks:

| Mask role | Meaning | Permitted use |
| --- | --- | --- |
| protect_structure | Material features, steps, grains, pores or fibres | Exclude from background estimation where appropriate; never reuse as an interpolation mask |
| trusted_background | Regions with defensible background support | Include in plane/background fitting, with conditioning and spatial coverage checks |
| repair_defect | Pixels or line segments diagnosed as acquisition defects | Repair only under the operation-specific policy; preserve an interpolation provenance mask |
| invalid_or_unknown | Missing, clipped or indeterminate measurements | Exclude from quantitative claims; do not silently reconstruct as measured data |

Each mask records its role, source channel, image version, coordinate grid, creation method, thresholds/parameters, physical scale, provenance and approval status. Reusing a mask after cropping, resampling or changing the underlying state requires an explicit coordinate transformation or regeneration and validation.

Generate several candidates from numerical segmentation, robust backgrounds, height/slope statistics and connected regions. Optional learned segmentation can add candidates, but does not define scientific truth. The planner chooses among identified candidate masks rather than writing arbitrary pixel arrays.

Mask thresholds need search and sensitivity analysis, not one universal percentage or an LLM's unverified numerical guess. A global background fit needs spatially distributed support and a well-conditioned fit. A row-wise correction needs support in the affected rows. Do not treat a per-row support criterion as a universal rule for all background fits. The current coverage cutoffs are provisional safeguards, not physical laws.

## 3. Closed-loop controller

Proposed cycle:

`inspect -> hypotheses -> mask candidates -> bounded processing trials -> quantitative/visual evaluation -> accept next state, revise, rollback or stop`

Use a state graph rather than blindly concatenating recipe lists. Each operation declares input channel types, mask roles, prerequisites, parameter bounds, expected effects, potential information loss and postconditions. Shared operations must not be accidentally applied twice by concatenating recipes.

For example, a surface with isolated objects and a line defect may require: provisional tilt estimate; protect-object and defect masks with different purposes; a supported masked fit; reevaluation of line residuals; localized repair only when warranted; structural preservation checks; then reference-zero and display settings. A stepped or continuous granular surface may require a different plan, or no correction. There is no universal cleaning order.

Every trial runs on a separate derivative. Maintain bounded trial count, time and memory; a no-change candidate is always allowed. If evidence remains ambiguous, return the best-supported provisional state and request review rather than repeatedly removing more structure.

## 4. Local executor and verifier

All numerical processing stays in the existing Gwyddion 32-bit/PyGwy bridge, with Python 3 orchestration. A model's structured plan is validated before execution. Reject unknown operations, stale masks, mismatched units, unsupported parameter ranges and excessive processing budgets.

The planner cannot submit arbitrary Python/shell code, select unrestricted filesystem paths, delete data, override policy gates or rewrite an approved result. Structured output guarantees syntax only; the local verifier still judges physical and operational validity.

Before/after assessment uses operation-specific quantities: background residuals, line discontinuities, feature heights relative to local substrate, edge geometry, protected-region changes, masks of interpolated pixels, roughness/PSD changes on meaningful regions, and registered trace/retrace agreement when available. Decreasing global Sq or matching a manual result pixel-for-pixel is not sufficient evidence of improvement.

Display rescaling remains separate from physical calibration and numerical correction. Never use a generative image restoration model as a source of measured topographic values.

## 5. Planner backends

Expose a single planner interface, independent of provider:

- Deterministic local planner: baseline and fallback, with measured candidate search.
- Local multimodal planner: candidate evaluation with a model such as Qwen3.5 4B or 9B served separately (for example through Ollama). Hardware latency, memory use and AFM quality must be measured on the workstation. Do not assume sufficient GPU resources from another user's computer.
- Optional remote multimodal planner: vision and schema-constrained tool calls, with the same local numerical executor and verifier. Provider/model selection requires comparative evaluation on this application's tasks, not general benchmark reputation.

API processing is opt-in, never an automatic fallback when the local service fails. Define the data disclosure boundary: numeric-only descriptions; anonymized previews plus descriptors; or separately authorized data. Removing filenames is not equivalent to removing scientific confidentiality. Network calls require explicit settings, retention review and budget limits. No raw archive bulk upload.

For the large corpus, first inventory and deduplicate, then group correlated acquisitions. Use fast local diagnosis broadly and deeper multimodal planning on representative or uncertain cases. Cache only where acquisition evidence and processing version justify reuse. Reusing a workflow across a series does not imply reusing the exact pixel mask.

## 6. Learning and validation

Keep the existing expert morphology labels. They can inform scene interpretation but do not supervise operation order, masks or repair quality. Candidate operator-corrected examples must be checked before being treated as reference targets; the operator has indicated some are not final.

Record accepted/rejected masks, parameter changes, the stage where each mask was used, operation order, before/after metrics and final review. Build a case library from verified decisions. Initially retrieve relevant precedents and compare bounded trials. Only consider training/distillation after accumulating validated action trajectories; never retrain from the agent's own unapproved outputs.

Evaluate three configurations on the same frozen cases: deterministic baseline, local VLM planner, optional API planner. Include synthetic surfaces with known ground truth and applied artifacts; real expert-approved regions; independent repeated-acquisition groups; and clearly reported unlabelled stress tests. Measure structural damage, residual defects, review rate, successful completion, latency and cost. Do not report supervised accuracy for the unlabelled archive.

## 7. Implementation order

1. Fix and isolate failing orchestration test fixtures without removing input/output separation guards. Distinguish mocked handoff tests from real Gwyddion numerical tests.
2. Add typed/versioned mask state and operation preconditions/postconditions; persist intermediate states and evidence.
3. Implement a bounded local candidate planner and evaluator that does not require manual recipe selection.
4. Add interchangeable local VLM/API planning providers in observation mode, comparing their proposed plans against the same evidence before enabling candidate execution.
5. Integrate the automatic workflow as the primary UI action; retain recipes and threshold editing in the advanced controls.


## 8. Blind 20-case planner benchmark (2026-11-12)

A first frozen comparison was run on 20 anonymized height maps. The external planner committed its plans and numerical outputs before manual references or deterministic AFM Copilot outputs were revealed. Manual corrections are still candidate expert references rather than certified ground truth, so these numbers are a proxy for agreement with existing expert work, not a physical-accuracy claim.

Deterministic AFM Copilot generated 16 candidates and held 4 because of the large-RMS-change gate. On the 16 cases where both systems produced a result, median manual-vs-candidate shape RMSE was about 20.0 nm for the deterministic candidate and 15.5 nm for the external planner result; mean RMSE was about 46.5 nm versus 31.6 nm. By the same simple RMSE-to-manual criterion, the external planner was closer on 9/16 cases and the deterministic candidate on 7/16.

The aggregate score hides the more important pattern:

- The external planner was substantially better on several hard routing cases involving whole-row offsets, repeated row/background correction, interrupted scans/cropping and cases where a no-change decision was appropriate.
- The deterministic path was safer or closer on several conservative cases, including a failed scar-repair attempt by the external planner and a strongly curved/featureless scan where the deterministic system correctly held instead of accepting an aggressive correction.
- Of the four deterministic holds, the external planner found useful partial corrections on three, but one hold was clearly safer than the external planner output. Therefore the large-RMS gate is not simply "too conservative"; it needs operation-specific evidence rather than global relaxation.
- Several cases showed that pixel RMSE alone is misleading: two outputs can preserve essentially identical morphology while differing mainly by a fitted plane, and a visually smoother result can still be scientifically inferior if it damages line/feature structure.

Decision: do not replace AFM Copilot with a free-form model and do not keep expanding the deterministic recipe router as the sole intelligence layer. The preferred architecture is hybrid: multimodal/LLM planning for diagnosis, routing, mask-role selection and trial proposals; deterministic Gwyddion execution; operation-specific verification and rollback; conservative hold/review when the verifier cannot defend the result.

The next engineering priority is therefore consolidation around one shared processing service and one case/plan schema. Benchmark helpers remain test tooling rather than a second application workflow. New directories or parallel processing paths require explicit justification and should not be added merely to support one experiment.

## Research and implementation references

These references support capabilities and engineering choices; they do not validate an AFM-specific model for this application.

- Gwyddion masks and include/exclude semantics: https://gwyddion.net/documentation/user-guide-en/presentations-masks.html
- Gwyddion levelling, polynomial background and automated Flatten Base: https://gwyddion.net/documentation/user-guide-en/leveling-and-background.html
- Gwyddion row correction cautions: https://gwyddion.net/documentation/user-guide-en/scan-line-defects.html
- Qwen3.5 model card: https://huggingface.co/Qwen/Qwen3.5-9B
- Ollama multimodal model variants: https://ollama.com/library/qwen3.5
- Ollama structured vision outputs: https://docs.ollama.com/capabilities/structured-outputs
- OpenAI function calling: https://developers.openai.com/api/docs/guides/function-calling
- OpenAI vision: https://developers.openai.com/api/docs/guides/images-vision
- OpenAI data controls: https://developers.openai.com/api/docs/guides/your-data
- Claude structured outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- AILA/AFMBench research: https://www.nature.com/articles/s41467-025-64105-7
- SAM 2 promptable segmentation (candidate generator, not metrological validation): https://ai.meta.com/research/sam2/
