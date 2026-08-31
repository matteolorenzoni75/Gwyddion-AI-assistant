"""
The operation catalog: Gwyddion functions with their meaning attached.

Each entry pairs a real, verified Gwyddion process function (every `gwy_func`
below was confirmed present by tools/introspect_pygwy.py) with the three things
a non-expert actually needs:

    what     what the operation does to the data
    why      the reason you would reach for it
    caution  when it is the wrong choice, and what it costs you

The `caution` field is the important one. Most AFM processing mistakes are not
wrong buttons, they are right buttons pressed on the wrong image -- a
polynomial background fitted through a real feature, or row levelling applied
to a surface whose long-wavelength structure was genuine. Encoding that here
means the app can warn before it acts, and explain afterwards.

Sources for the cautions are in docs/research/ARTIFACT_TAXONOMY.md and
docs/research/QUALITY_METRICS.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Gwyddion's Align Rows methods, as used by the proven code in the previous
# project. The settings key is /module/linematch/method.
LINEMATCH_MEDIAN = 1
LINEMATCH_MEDIAN_OF_DIFF = 4


@dataclass(frozen=True)
class Operation:
    """One Gwyddion operation, with the knowledge needed to use it well."""

    key: str
    gwy_func: str
    title: str
    what: str
    why: str
    caution: str | None = None
    menu: str = ""
    settings: dict = field(default_factory=dict)
    needs_mask: bool = False
    creates_mask: bool = False

    def explain(self) -> str:
        """A short human-readable account, for logs, reports and the UI."""
        lines = [f"{self.title}  (Gwyddion: {self.gwy_func})",
                 f"  What: {self.what}",
                 f"  Why:  {self.why}"]
        if self.caution:
            lines.append(f"  Note: {self.caution}")
        return "\n".join(lines)


_ALL: list[Operation] = [
    Operation(
        key="plane_level",
        gwy_func="level",
        title="Subtract mean plane",
        menu="/Level/Plane Level",
        what="Fits a flat plane through the whole image and subtracts it.",
        why="Removes the tilt that comes from the sample not sitting exactly "
            "perpendicular to the tip. Almost every scan needs it, and nothing "
            "downstream works properly until it is done.",
        caution="It subtracts a plane rather than rotating the data, so true "
                "facet angles are slightly distorted. Use Level Rotate instead "
                "if you are measuring angles.",
    ),
    Operation(
        key="level_rotate",
        gwy_func="level_rotate",
        title="Level by rotation",
        menu="/Level/Level Rotate",
        what="Removes tilt by rotating the data instead of subtracting a plane.",
        why="Preserves real surface angles, so it is the correct choice when "
            "facet or sidewall angles are part of the measurement.",
        caution="Slower and slightly resamples the data. For routine flattening "
                "plain Plane Level is fine.",
    ),
    Operation(
        key="polynomial_background",
        gwy_func="polylevel",
        title="Remove polynomial background",
        menu="/Level/Polynomial Background",
        what="Fits a curved (polynomial) surface to the whole image and "
             "subtracts it.",
        why="Removes scanner bow -- the dish or dome shape that piezo tube "
            "scanners add because the tip moves on an arc, not a plane.",
        caution="This is the single largest source of roughness error in AFM. "
                "Each extra polynomial order removes more real long-wavelength "
                "structure along with the bow: at a scan-length-to-correlation-"
                "length ratio of 15, a 3rd-order fit underestimates roughness by "
                "about 40%. Use the lowest order that removes the bow, and treat "
                "roughness measured afterwards as a lower bound.",
    ),
    Operation(
        key="flatten_base",
        gwy_func="flatten_base",
        title="Flatten base (feature-aware)",
        menu="/Level/Flatten Base",
        what="Combines facet levelling and polynomial levelling, automatically "
             "masking out prominent raised features so they do not bias the fit.",
        why="The right choice when objects stand above the surface -- particles, "
            "flakes, islands. Ordinary levelling fits a plane *through* those "
            "objects and leaves dark halos around them; this fits the background "
            "only.",
        caution="Assumes the features of interest are raised above a flat base. "
                "On a surface that is genuinely curved everywhere, or where "
                "features are recessed, it has nothing sensible to fit to.",
    ),
    Operation(
        key="align_rows_median_diff",
        gwy_func="align_rows",
        title="Align rows (median of differences)",
        menu="/Correct Data/Align Rows",
        what="Removes the constant height offset between neighbouring scan "
             "lines, by forcing the median height *difference* between adjacent "
             "rows to zero.",
        why="Fixes the horizontal banding that comes from feedback drift within "
            "a line. The median-of-differences method is used rather than plain "
            "median because it preserves large features -- a plain median shifts "
            "any row that happens to cross a tall object.",
        caution="Row-wise corrections damage roughness far more than whole-image "
                "ones (the error grows linearly with correlation length, not "
                "quadratically). If the horizontal structure in your surface is "
                "real, this will remove it. Skip it for surfaces with genuine "
                "long-wavelength waviness along the slow axis.",
        settings={
            "/module/linematch/method": LINEMATCH_MEDIAN_OF_DIFF,
            "/module/linematch/do_extract": False,
            "/module/linematch/do_plot": False,
        },
    ),
    Operation(
        key="align_rows_median",
        gwy_func="align_rows",
        title="Align rows (median)",
        menu="/Correct Data/Align Rows",
        what="Shifts each scan line so that its median height is zero.",
        why="A blunter, very robust row correction for badly banded images "
            "where the surface is essentially flat.",
        caution="Destroys real long-wavelength structure more aggressively than "
                "median-of-differences. Prefer that one unless it fails.",
        settings={
            "/module/linematch/method": LINEMATCH_MEDIAN,
            "/module/linematch/do_extract": False,
            "/module/linematch/do_plot": False,
        },
    ),
    Operation(
        key="remove_scars",
        gwy_func="scars_remove",
        title="Remove scars",
        menu="/Correct Data/Remove Scars",
        what="Finds short horizontal streaks that are anomalous compared with "
             "the rows immediately above and below, and interpolates them away.",
        why="Scars come from the feedback loop briefly losing control, or the "
            "tip picking up and dropping debris. They are pure artifact and "
            "they distort every statistic computed afterwards.",
        caution="A scar is defined as being inconsistent with its neighbouring "
                "rows. Genuinely thin, horizontal, real features can match that "
                "description -- check the result if your sample has fine "
                "horizontal structure.",
    ),
    Operation(
        key="mark_outliers",
        gwy_func="outliers",
        title="Mark outliers",
        menu="/Correct Data/Mask of Outliers",
        what="Creates a mask covering every pixel more than three standard "
             "deviations from the mean.",
        why="Isolates spikes and dropouts -- single bad pixels from electrical "
            "glitches or momentary loss of contact -- so they can be repaired "
            "without touching anything else.",
        caution="On a surface with genuine tall features, those features are "
                "also more than 3 sigma from the mean and will be masked. This "
                "is for cleaning noise, not for segmenting objects.",
        creates_mask=True,
    ),
    Operation(
        key="interpolate_under_mask",
        gwy_func="laplace",
        title="Repair masked pixels",
        menu="/Correct Data/Interpolate Data Under Mask",
        what="Replaces every masked pixel with a smooth surface computed from "
             "the surrounding good data (solution of the Laplace equation).",
        why="Repairs the spikes and dropouts found in the previous step without "
            "blurring the rest of the image -- which is what a global smoothing "
            "filter would do.",
        caution="The repaired pixels are interpolated, not measured. Do not "
                "quote measurements taken from them.",
        needs_mask=True,
    ),
    Operation(
        key="remove_mask",
        gwy_func="mask_remove",
        title="Clear the mask",
        menu="/Mask/Remove Mask",
        what="Discards the working mask.",
        why="Tidies up after a mask-based repair so the mask is not carried "
            "into later steps or saved into the output file.",
    ),
    Operation(
        key="fix_zero",
        gwy_func="fix_zero",
        title="Set minimum to zero",
        menu="/Level/Fix Zero",
        what="Shifts the whole image so its lowest point sits at zero height.",
        why="Gives every image a common, meaningful zero, which is what makes a "
            "batch comparable and what lets heights be read straight off the "
            "colour bar.",
        caution="Ties the zero to the single lowest pixel, so a negative spike "
                "will offset the whole image. Repair spikes first.",
    ),
    Operation(
        key="zero_mean",
        gwy_func="zero_mean",
        title="Set mean to zero",
        menu="/Level/Zero Mean Value",
        what="Shifts the image so its average height is zero.",
        why="More robust than Fix Zero when the image has spikes, and the "
            "conventional choice before computing roughness.",
    ),
]

OPERATIONS: dict[str, Operation] = {op.key: op for op in _ALL}


def get_operation(key: str) -> Operation:
    try:
        return OPERATIONS[key]
    except KeyError:
        raise KeyError(
            f"Unknown operation {key!r}. Known operations: "
            + ", ".join(sorted(OPERATIONS))) from None
