"""Generate competing Gwyddion grain masks without changing the height map.

The question ``what is background?`` cannot honestly be answered by one
height threshold.  Gwyddion already implements several independent ways to
mark a grain.  This module runs them as *proposals*: each output is a separate
``.gwy`` with the original height data plus one candidate mask.  Nothing is
levelled, interpolated, or removed at this stage.

The next stage (visual review, an operator mask, or a vision model) judges the
candidate against the topography.  Numerical checks here only reject masks
that are geometrically unusable for a background fit; they never claim that a
mask describes a particle merely because it has a convenient area.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy import ndimage

from afm_copilot.bridge import GwyBridge
from afm_copilot.gwy_io import load_height, load_mask


@dataclass(frozen=True)
class MaskMethod:
    """One independently parameterised Gwyddion grain-marking proposal."""

    key: str
    title: str
    gwy_func: str
    settings: dict
    rationale: str


# Parameters are Gwyddion 2.70's documented module settings (not guessed UI
# labels).  The alternatives deliberately disagree: agreement is useful
# evidence, while disagreement is exactly what a vision review must inspect.
DEFAULT_METHODS: tuple[MaskMethod, ...] = (
    MaskMethod(
        key="height_high",
        title="Raised grains, conservative height threshold",
        gwy_func="grain_mark",
        settings={
            "/module/grain_mark/isheight": True,
            "/module/grain_mark/height": 0.70,
            "/module/grain_mark/isslope": False,
            "/module/grain_mark/islap": False,
            "/module/grain_mark/isrank": False,
            "/module/grain_mark/inverted": False,
            "/module/grain_mark/combine": False,
        },
        rationale="Compact objects well above a mostly flat base.",
    ),
    MaskMethod(
        key="height_mid",
        title="Raised grains, inclusive height threshold",
        gwy_func="grain_mark",
        settings={
            "/module/grain_mark/isheight": True,
            "/module/grain_mark/height": 0.55,
            "/module/grain_mark/isslope": False,
            "/module/grain_mark/islap": False,
            "/module/grain_mark/isrank": False,
            "/module/grain_mark/inverted": False,
            "/module/grain_mark/combine": False,
        },
        rationale="Objects whose shoulders fall below a conservative height cut.",
    ),
    MaskMethod(
        key="slope",
        title="Grain boundaries from slope",
        gwy_func="grain_mark",
        settings={
            "/module/grain_mark/isheight": False,
            "/module/grain_mark/isslope": True,
            "/module/grain_mark/slope": 0.50,
            "/module/grain_mark/islap": False,
            "/module/grain_mark/isrank": False,
            "/module/grain_mark/inverted": False,
            "/module/grain_mark/combine": False,
        },
        rationale="Edges of grains when height alone merges them into the base.",
    ),
    MaskMethod(
        key="curvature",
        title="Grain boundaries from curvature",
        gwy_func="grain_mark",
        settings={
            "/module/grain_mark/isheight": False,
            "/module/grain_mark/isslope": False,
            "/module/grain_mark/islap": True,
            "/module/grain_mark/lap": 0.50,
            "/module/grain_mark/isrank": False,
            "/module/grain_mark/inverted": False,
            "/module/grain_mark/combine": False,
        },
        rationale="Rims and compact peaks whose contrast is local, not global.",
    ),
    MaskMethod(
        key="edge",
        title="Grain boundaries by edge detection",
        gwy_func="grain_edge",
        settings={"/module/grain_edge/threshold_laplacian": 0.50,
                  "/module/grain_edge/combine": False},
        rationale="Difference-of-Gaussians edge proposal for shape-defined grains.",
    ),
    MaskMethod(
        key="otsu",
        title="Two-population Otsu mask",
        gwy_func="otsu-threshold",
        settings={},
        rationale="Two clearly separated height populations, such as a film step.",
    ),
    MaskMethod(
        key="watershed",
        title="Watershed-separated grains",
        gwy_func="grain_wshed",
        settings={
            "/module/grain_wshed/inverted": False,
            "/module/grain_wshed/locate_steps": 10,
            "/module/grain_wshed/locate_thresh": 10,
            "/module/grain_wshed/locate_dropsize": 0.10,
            "/module/grain_wshed/wshed_steps": 20,
            "/module/grain_wshed/wshed_dropsize": 0.10,
            "/module/grain_wshed/combine": False,
        },
        rationale="Touching or agglomerated grains that a threshold cannot split.",
    ),
)


def mask_statistics(mask: np.ndarray) -> dict[str, float | int]:
    """Shape evidence a reviewer needs before accepting a mask proposal."""
    marked = np.asarray(mask, dtype=bool)
    if marked.ndim != 2 or not marked.any():
        return {"fraction": 0.0, "grains": 0, "median_area_px": 0.0,
                "edge_touching_grains": 0}
    labels, count = ndimage.label(marked)
    areas = np.bincount(labels.ravel())[1:]
    border = np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1]))
    touching = set(int(value) for value in border if value)
    return {
        "fraction": round(float(marked.mean()), 6),
        "grains": int(count),
        "median_area_px": round(float(np.median(areas)), 3),
        "edge_touching_grains": len(touching),
    }


def propose(paths: list[str | Path], out: str | Path,
            methods: tuple[MaskMethod, ...] = DEFAULT_METHODS,
            bridge: GwyBridge | None = None) -> dict:
    """Run every grain-marking method on independent copies of each map.

    The returned manifest carries the output path and objective geometry for
    every candidate.  The caller remains responsible for semantic acceptance.
    """
    sources = [Path(path) for path in paths]
    out_dir = Path(out)
    candidate_dir = out_dir / "candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for index, source in enumerate(sources, 1):
        for method in methods:
            jobs.append({
                "source": str(source),
                "method": asdict(method),
                # Blind, collision-free output names deliberately avoid
                # teaching any later classifier from a filename.
                "output": str(candidate_dir / f"scan-{index:04d}--{method.key}.gwy"),
            })

    job_path = out_dir / "mask-proposals-job.json"
    job_path.write_text(json.dumps({"jobs": jobs}, indent=2), encoding="utf-8")
    report = (bridge or GwyBridge()).run_script(
        "propose_masks.py", ["--job", str(job_path)], timeout=1800.0)

    records = []
    for record in report.get("results", []):
        output = Path(record.get("output", ""))
        if record.get("ok") and output.is_file():
            try:
                mask = load_mask(output, load_height(output))
            except (OSError, ValueError):
                mask = None
            record["statistics"] = mask_statistics(mask) if mask is not None else None
            if mask is None:
                record["ok"] = False
                record["error"] = "Gwyddion produced no readable mask"
        records.append(record)

    manifest = {
        "sources": len(sources),
        "methods": [asdict(method) for method in methods],
        "results": records,
        "n_masks": sum(1 for record in records if record.get("ok")),
    }
    review = render_review(manifest, out_dir / "mask-proposals-review.png")
    if review is not None:
        manifest["review_image"] = str(review)
    (out_dir / "mask-proposals.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def render_review(manifest: dict, path: str | Path) -> Path | None:
    """Render raw height plus each candidate as a reviewable mask overlay.

    The image is deliberately a contact sheet instead of an automatic winner.
    A vision model (or a human) needs to see whether a highlighted boundary
    follows a particle, a terrace edge, a feedback tail, or merely texture.
    """
    records = [record for record in manifest.get("results", [])
               if record.get("ok") and record.get("statistics")]
    sources = list(dict.fromkeys(record["source"] for record in records))
    if not records or not sources:
        return None
    methods = [method["key"] for method in manifest.get("methods", [])]
    figure, axes = plt.subplots(len(sources), len(methods) + 1,
                                figsize=(2.15 * (len(methods) + 1),
                                         2.35 * len(sources)), squeeze=False)
    by_source_method = {(record["source"], record["method"]): record
                        for record in records}
    for row, source in enumerate(sources):
        try:
            data = np.asarray(load_height(source).data, dtype=float)
            low, high = np.nanpercentile(data, (1.0, 99.0))
        except (OSError, ValueError):
            continue
        axes[row, 0].imshow(data, cmap="afmhot", vmin=low, vmax=high,
                            interpolation="nearest")
        axes[row, 0].set_title("height", fontsize=9)
        axes[row, 0].axis("off")
        for column, method in enumerate(methods, 1):
            axis = axes[row, column]
            axis.imshow(data, cmap="afmhot", vmin=low, vmax=high,
                        interpolation="nearest")
            record = by_source_method.get((source, method))
            if record:
                try:
                    mask = load_mask(record["output"], load_height(record["output"]))
                except (OSError, ValueError):
                    mask = None
                if mask is not None:
                    overlay = np.ma.masked_where(~mask, mask)
                    axis.imshow(overlay, cmap="cool", alpha=0.60,
                                interpolation="nearest", vmin=0, vmax=1)
                stats = record["statistics"]
                axis.set_title(f"{method}\n{stats['fraction']:.1%}, "
                               f"n={stats['grains']}", fontsize=8)
            else:
                axis.set_title(f"{method}\n(no mask)", fontsize=8)
            axis.axis("off")
    figure.suptitle("Candidate masks: cyan is proposed exclusion from background fit",
                     fontsize=12)
    figure.tight_layout()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return destination
