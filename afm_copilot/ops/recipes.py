"""
Recipes: the four or five routine Gwyddion operations people always run
together, bundled into one named action.

Ordering is not arbitrary. It follows the sequence the processing literature
supports and that the previous project established:

    level / flatten  ->  row and scar corrections  ->  denoise  ->  baseline

Flattening comes before denoising, never the reverse, because a tilted or bowed
surface puts spurious low-frequency power into the spectrum that a denoiser
would then chase. Spike repair comes before anything that uses the minimum or
the mean, because one bad pixel moves both.

Each recipe states the problem it solves and when it is the wrong tool, so the
app can explain its choice rather than just making one.
"""

from __future__ import annotations

from dataclasses import dataclass

from afm_copilot.ops.catalog import Operation, get_operation


@dataclass(frozen=True)
class Recipe:
    """A named sequence of operations, with the reasoning attached."""

    key: str
    title: str
    purpose: str
    when_to_use: str
    when_not_to_use: str
    steps: tuple[str, ...]

    @property
    def operations(self) -> list[Operation]:
        return [get_operation(k) for k in self.steps]

    def explain(self) -> str:
        """Full plain-language account of what this recipe will do and why."""
        lines = [
            f"{self.title}",
            "=" * len(self.title),
            "",
            f"Purpose:  {self.purpose}",
            f"Use when: {self.when_to_use}",
            f"Avoid if: {self.when_not_to_use}",
            "",
            f"Steps ({len(self.steps)}):",
        ]
        for i, op in enumerate(self.operations, 1):
            lines.append("")
            lines.append(f"  {i}. {op.title}   [{op.gwy_func}]")
            lines.append(f"     What: {op.what}")
            lines.append(f"     Why:  {op.why}")
            if op.caution:
                lines.append(f"     Note: {op.caution}")
        return "\n".join(lines)

    def to_job(self) -> list[dict]:
        """The machine-readable form handed to the Python 2.7 side."""
        return [
            {
                "key": op.key,
                "gwy_func": op.gwy_func,
                "title": op.title,
                "settings": dict(op.settings),
                "needs_mask": op.needs_mask,
                "creates_mask": op.creates_mask,
            }
            for op in self.operations
        ]


_ALL: list[Recipe] = [
    Recipe(
        key="quick-clean",
        title="Quick clean",
        purpose="The routine tidy-up that most scans need before anything else: "
                "remove tilt, straighten the scan lines, repair scars, and set a "
                "meaningful zero.",
        when_to_use="Any reasonably flat scan you want to look at, measure or "
                    "put in a figure. This is the sensible default.",
        when_not_to_use="Scans dominated by tall objects -- use 'clean with "
                        "features' instead, which masks them out before fitting. "
                        "Also avoid before a roughness measurement, where the row "
                        "correction costs accuracy; use 'roughness ready'.",
        steps=(
            "plane_level",
            "align_rows_median_diff",
            "remove_scars",
            "fix_zero",
        ),
    ),
    Recipe(
        key="clean-with-features",
        title="Clean, protecting raised features",
        purpose="Flatten the background without letting particles, flakes or "
                "islands drag the fit, then apply the usual line and scar "
                "corrections.",
        when_to_use="Anything with objects standing above a substrate: "
                    "nanoparticles, flakes, deposited films, biological objects "
                    "on mica.",
        when_not_to_use="Genuinely curved surfaces with no flat base, or samples "
                        "where the features are pits rather than bumps.",
        steps=(
            "plane_level",
            "flatten_base",
            "align_rows_median_diff",
            "remove_scars",
            "fix_zero",
        ),
    ),
    Recipe(
        key="despike",
        title="Repair spikes and dropouts",
        purpose="Find single bad pixels and replace them with interpolated "
                "values, without smoothing the rest of the image.",
        when_to_use="Images with isolated bright or dark points from electrical "
                    "glitches, dust or momentary loss of contact.",
        when_not_to_use="Surfaces whose real features are small and tall -- the "
                        "3-sigma test cannot tell those from spikes.",
        steps=(
            "mark_outliers",
            "interpolate_under_mask",
            "remove_mask",
        ),
    ),
    Recipe(
        key="roughness-ready",
        title="Prepare for roughness measurement",
        purpose="Remove form and bow with the least possible damage to the "
                "roughness you are about to measure.",
        when_to_use="Before quoting Sq, Sa or a PSD. Uses whole-image levelling "
                    "only and deliberately omits row-by-row correction, because "
                    "row-wise corrections bias roughness far more heavily.",
        when_not_to_use="Images with visible scan-line banding -- that banding "
                        "will be counted as roughness. Fix the acquisition, or "
                        "accept the bias knowingly.",
        steps=(
            "plane_level",
            "polynomial_background",
            "remove_scars",
            "zero_mean",
        ),
    ),
    Recipe(
        key="level-only",
        title="Level only",
        purpose="The most conservative option: remove tilt and set a zero, "
                "nothing else.",
        when_to_use="When you want to see the data almost as measured, or as a "
                    "first look before deciding what it actually needs.",
        when_not_to_use="When the image has obvious banding or scars -- this "
                        "will not touch them.",
        steps=(
            "plane_level",
            "fix_zero",
        ),
    ),
]

RECIPES: dict[str, Recipe] = {r.key: r for r in _ALL}


def get_recipe(key: str) -> Recipe:
    try:
        return RECIPES[key]
    except KeyError:
        raise KeyError(
            f"Unknown recipe {key!r}. Available recipes: "
            + ", ".join(sorted(RECIPES))) from None
