"""Human/vision morphology reviews that can make processing more cautious.

The numerical pipeline deliberately does not pretend that every semantic
distinction is recoverable from one scalar threshold.  A review can therefore
veto an unsafe interpretation (for example, calling a close-packed granular
surface isolated objects on a background).  It cannot, by itself, authorise a
more aggressive correction.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy import ndimage


FAMILIES = frozenset({
    "isolated_objects",
    "terraces",
    "granular_continuous",
    "pores",
    "fibres",
    "periodic",
    "uncertain",
})
EFFECTS = frozenset({"advisory", "restrict"})


@dataclass(frozen=True)
class MorphologyReview:
    """A named, auditable semantic observation about one scan."""

    scan: str
    family: str
    effect: str = "advisory"
    source: str = "review"
    evidence: tuple[str, ...] = ()

    @property
    def restricts_automatic_masking(self) -> bool:
        """Only the presently validated veto has processing consequences."""
        return self.effect == "restrict" and self.family == "granular_continuous"


@dataclass(frozen=True)
class BackgroundSupport:
    """Evidence that a proposed mask leaves a real, measurable background.

    These are descriptors, not an automatic semantic verdict.  A convenient
    mask area is not proof that the remaining pixels are a substrate: on a
    close-packed granular film the threshold often marks only the gaps and
    calls the grains themselves "background".  The ratios below expose that
    failure before any row or polynomial correction is authorised.
    """

    valid: bool
    unmasked_fraction: float
    worst_row_support: float
    largest_region_fraction: float
    roughness_ratio: float
    gradient_ratio: float
    texture_coverage: float

    def as_dict(self) -> dict[str, bool | float]:
        return asdict(self)


def background_support(data: np.ndarray, mask: np.ndarray,
                       cells: int = 8) -> BackgroundSupport:
    """Measure the substrate left outside a proposed feature mask.

    ``roughness_ratio`` and ``gradient_ratio`` compare the unmasked region with
    the complete levelled surface.  They approach zero for compact objects on
    a quiet substrate and one when the alleged background still carries most
    of the morphology.  ``texture_coverage`` asks how much of the frame keeps
    appreciable local relief after masked pixels are excluded.  No threshold
    here chooses a family; the blind-corpus survey must establish whether the
    descriptors actually separate cases before they can affect routing.
    """
    values = np.asarray(data, dtype=float)
    marked = np.asarray(mask, dtype=bool)
    if values.ndim != 2 or marked.shape != values.shape:
        raise ValueError("background support needs equally shaped 2-D data and mask")

    finite = np.isfinite(values)
    usable = finite & ~marked
    unmasked_fraction = float(usable.mean()) if usable.size else 0.0
    row_support = usable.mean(axis=1) if usable.size else np.asarray([0.0])
    worst_row_support = float(row_support.min()) if row_support.size else 0.0

    labels, count = ndimage.label(usable)
    if count:
        areas = np.bincount(labels.ravel())[1:]
        largest_region_fraction = float(areas.max() / max(1, usable.sum()))
    else:
        largest_region_fraction = 0.0

    enough = usable.sum() >= max(1024, int(0.40 * values.size))
    if not enough or finite.sum() < 1024:
        return BackgroundSupport(
            valid=False,
            unmasked_fraction=unmasked_fraction,
            worst_row_support=worst_row_support,
            largest_region_fraction=largest_region_fraction,
            roughness_ratio=float("nan"),
            gradient_ratio=float("nan"),
            texture_coverage=float("nan"),
        )

    fill = float(np.nanmedian(values))
    filled = np.where(finite, values, fill)
    full_scale = float(np.nanstd(values[finite]))
    background_scale = float(np.nanstd(values[usable]))
    roughness_ratio = (background_scale / full_scale
                       if full_scale > 0 else 0.0)

    smooth = ndimage.gaussian_filter(filled, sigma=1.0)
    dy, dx = np.gradient(smooth)
    gradient = np.hypot(dx, dy)
    full_gradient = float(np.median(gradient[finite]))
    background_gradient = float(np.median(gradient[usable]))
    gradient_ratio = (background_gradient / full_gradient
                      if full_gradient > 0 else 0.0)

    local_spread: list[float] = []
    local_support: list[float] = []
    for rows in np.array_split(np.arange(values.shape[0]), cells):
        for columns in np.array_split(np.arange(values.shape[1]), cells):
            take = usable[np.ix_(rows, columns)]
            local_support.append(float(take.mean()))
            tile = values[np.ix_(rows, columns)][take]
            if tile.size >= max(16, int(0.40 * take.size)):
                lo, hi = np.percentile(tile, (10.0, 90.0))
                local_spread.append(float(hi - lo))
            else:
                local_spread.append(float("nan"))
    spreads = np.asarray(local_spread, dtype=float)
    support = np.asarray(local_support, dtype=float)
    measurable = np.isfinite(spreads) & (support >= 0.40)
    if measurable.any():
        reference = float(np.percentile(spreads[measurable], 90.0))
        texture_coverage = (float(np.mean(spreads[measurable]
                                          >= 0.25 * reference))
                            if reference > 0 else 0.0)
    else:
        texture_coverage = float("nan")

    return BackgroundSupport(
        valid=True,
        unmasked_fraction=unmasked_fraction,
        worst_row_support=worst_row_support,
        largest_region_fraction=largest_region_fraction,
        roughness_ratio=roughness_ratio,
        gradient_ratio=gradient_ratio,
        texture_coverage=texture_coverage,
    )


def load_reviews(path: str | Path) -> dict[str, MorphologyReview]:
    """Read reviews from JSON, indexed by the exact scan stem.

    Accepted input is either a list of review objects or ``{"reviews": [...]}``.
    Validation is intentionally strict: an ignored typo in a safety veto is
    worse than refusing to start.
    """
    source_path = Path(path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    records = payload.get("reviews") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("morphology reviews must be a list or {'reviews': [...]}")

    reviews: dict[str, MorphologyReview] = {}
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"morphology review {index} is not an object")

        raw_scan = record.get("scan")
        family = record.get("family")
        effect = record.get("effect", "advisory")
        source = record.get("source", "review")
        evidence = record.get("evidence", [])

        if not isinstance(raw_scan, str) or not raw_scan.strip():
            raise ValueError(f"morphology review {index} has no scan name")
        scan = Path(raw_scan.strip()).stem
        if family not in FAMILIES:
            raise ValueError(
                f"morphology review {scan!r} has unknown family {family!r}; "
                f"choose one of {', '.join(sorted(FAMILIES))}")
        if effect not in EFFECTS:
            raise ValueError(
                f"morphology review {scan!r} has unknown effect {effect!r}; "
                f"choose one of {', '.join(sorted(EFFECTS))}")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"morphology review {scan!r} has no source")
        if (not isinstance(evidence, list)
                or any(not isinstance(item, str) or not item.strip()
                       for item in evidence)):
            raise ValueError(
                f"morphology review {scan!r} evidence must be a list of text")
        if scan in reviews:
            raise ValueError(f"duplicate morphology review for {scan!r}")

        reviews[scan] = MorphologyReview(
            scan=scan,
            family=family,
            effect=effect,
            source=source.strip(),
            evidence=tuple(item.strip() for item in evidence),
        )
    return reviews


def save_reviews(path: str | Path,
                 reviews: Iterable[MorphologyReview]) -> Path:
    """Write reviews atomically in the same auditable format the CLI reads."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(reviews, key=lambda review: review.scan.casefold())
    payload = {"reviews": [{
        "scan": review.scan,
        "family": review.family,
        "effect": review.effect,
        "source": review.source,
        "evidence": list(review.evidence),
    } for review in ordered]}
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def upsert_review(path: str | Path, review: MorphologyReview) -> Path:
    """Add or replace one scan's review without losing the rest of its batch."""
    destination = Path(path)
    existing = load_reviews(destination) if destination.is_file() else {}
    existing[review.scan] = review
    return save_reviews(destination, existing.values())
