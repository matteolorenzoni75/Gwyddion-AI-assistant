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
        key="facet-terraces",
        title="Level distinct terraces by their facets",
        purpose="Orient a stepped or terraced surface with its facets upright, "
                "without fitting a curved background through its step heights.",
        when_to_use="Only when the strict height-histogram test finds two or "
                    "more narrow, clearly separated levels.",
        when_not_to_use="Particle fields, fibre networks, broad slopes or a "
                        "single rough population.  These are not terraces even "
                        "when their height range is large.",
        steps=(
            "facet_level",
            "remove_scars",
            "fix_zero",
        ),
    ),
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
        key="isolate-objects",
        title="Correct the background around raised objects",
        purpose="Mark whatever stands above the surface, correct the "
                "background using only the surface around it, and leave the "
                "objects themselves untouched by the fit.",
        when_to_use="The common case: objects sitting on a substrate that is "
                    "flat apart from instrument bow — a silicon wafer or mica. "
                    "Particles, flakes, crystals, deposited islands.",
        when_not_to_use="Surfaces with no distinct background, where features "
                        "merge gradually into the substrate, or where the "
                        "structure of interest is recessed rather than raised. "
                        "Also check the mask if the objects cover much of the "
                        "frame — there may not be enough background left to fit.",
        # The mask arrives with the file -- see 'isolate objects, flat'.
        # No row correction here. See 'isolate objects, flat' -- the masked
        # version was measured to spoil 30 of 79 scans and there is no test
        # that says in advance which 30.
        steps=(
            "plane_level",
            "background_around_objects",
            "remove_mask",
            "align_rows_median_diff",
            # Scars are never the sample: a stroke dragged along the fast axis
            # is the tip losing and regaining the surface. This step was
            # missing here, so 60 scans of a 197-scan batch went through with
            # their strokes intact while the 107 on 'quick clean' had them
            # repaired.
            "remove_scars",
            "fix_zero",
        ),
    ),
    Recipe(
        key="isolate-objects-flat",
        title="Level the background around objects, without adding curvature",
        purpose="Mark whatever stands above the surface and fit a plane to the "
                "background alone, leaving the objects out of the fit.",
        when_to_use="Objects on a background that measures flat. The masking "
                    "is what matters here: a tall object left in the fit tilts "
                    "the plane towards itself and the base comes out sloped.",
        when_not_to_use="Backgrounds with real curvature — use 'isolate "
                        "objects', which fits a curved surface around the same "
                        "mask.",
        # No marking step: the mask arrives with the file, built by this
        # project's own detector rather than by a height threshold. The two
        # disagreed four to one on a real scan, and a background fitted around
        # the wrong region came out worse than one fitted around nothing.
        # The masked row correction used to sit here, between the background
        # fit and clearing the mask. It is gone, and the measurement is the
        # reason. Collapsing each frame to its mean profile down the slow axis
        # and removing a straight line leaves the curvature; on the batch that
        # curvature GREW on 30 of the 79 scans on this route, by up to 156 nm,
        # and on none of the scans that never saw a mask.
        #
        # Run the same file with Gwyddion's three masking modes and it is not
        # subtle: 0 and 1 give bellies of 43 and 107 nm, "no mask at all" gives
        # 0.34. A line correction judges each row from its own background, and
        # our masks cover a third to a half of the frame -- whole rows have no
        # background left in them, and the offset for those rows is invented.
        #
        # Nor is there a rule that saves it. Admitting only scans whose worst
        # row keeps 60% clear still spoils 8 of the 23 admitted; at 40% it
        # still spoils 1 of 4. A correction that harms unpredictably does not
        # run unasked -- which leaves the masked background fit, the part that
        # works and the part that was asked for.
        #
        # The operation stays in the catalog. With a tight mask drawn around
        # one object by hand it is the right tool, and that is how the user
        # reached a good result on this very scan.
        steps=(
            "plane_level",
            "plane_around_objects",
            "remove_mask",
            # The ordinary row correction, after the mask is gone. It is the
            # masked variant that was dangerous, not the correction: across
            # the batch the plain one put a belly into none of the scans that
            # ran it. One scan arrived with 150 nm of curvature along the slow
            # axis and lost every bit of it when the masked step was removed,
            # which is the repair this puts back.
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
