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
        key="grow_mask",
        gwy_func="mask_morph",
        title="Grow the mask over the object's flanks",
        menu="/Mask/Morphological Operation",
        what="Widens the existing mask by a few pixels in every direction.",
        why="A threshold marks the top of an object and stops at its shoulder, "
            "leaving the flanks in the background. Those flanks are largely "
            "the tip's own shape smeared around the object -- roughly a tip "
            "radius wide -- so they are neither background nor reliable "
            "sample, and letting them into the fit is what the user sees as "
            "edges that are still not right.",
        caution="Grows every mark, so on a crowded surface it can merge "
                "neighbouring objects and leave too little background to fit "
                "on. Keep the radius near the tip radius in pixels.",
        needs_mask=True,
        settings={
            # Only the radius is set. The module's default operation was
            # verified to dilate -- a mask of 206187 pixels came back at
            # 209013 -- so the mode is left as Gwyddion has it rather than
            # guessing at an enum value that means something else.
            "/module/mask_morph/radius": 3,
        },
    ),
    Operation(
        key="align_rows_around_objects",
        gwy_func="align_rows",
        title="Align rows, ignoring the marked objects",
        menu="/Correct Data/Align Rows",
        what="The same row correction, with every marked pixel left out of it: "
             "each row's offset is judged from its background alone.",
        why="A large object breaks the ordinary version. Median-of-differences "
            "survives a *narrow* feature crossing a row, but when the object "
            "covers much of the line the median difference is the object's "
            "own slope, and the correction writes that slope into the "
            "background. The user reached a good result on exactly this scan "
            "by masking the block by hand and only then aligning rows -- so "
            "the mask has to still be there when this runs, which means "
            "clearing it comes afterwards, not before.",
        caution="Needs a TIGHT mask around one object, drawn by someone who "
                "can see it. Not for automatic use: with the masks this "
                "project builds -- a third to a half of the frame -- whole "
                "rows keep no background, their offset is invented, and the "
                "surface comes back with a belly along the slow axis. "
                "Measured across the batch: curvature grew on 30 of the 79 "
                "masked scans, by up to 156 nm, and on none of the unmasked "
                "ones. No threshold on mask coverage separates the 30 from "
                "the rest, so it is out of the automatic recipes.",
        needs_mask=True,
        settings={
            "/module/linematch/method": LINEMATCH_MEDIAN_OF_DIFF,
            "/module/linematch/do_extract": False,
            "/module/linematch/do_plot": False,
            # 0 is MASK_EXCLUDE: marked pixels take no part in the fit.
            "/module/linematch/masking": 0,
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
        key="mark_raised_objects",
        gwy_func="grain_mark",
        title="Mark the objects standing above the surface",
        menu="/Grains/Mark by Threshold",
        what="Marks every region rising more than a set fraction of the height "
             "range above the rest, and covers it with a mask.",
        why="This is the step that separates the objects from the surface they "
            "sit on. Once they are marked, the background underneath can be "
            "corrected without the objects taking part in the fit.",
        caution="The threshold is a fraction of the height range, so it adapts "
                "to each scan — but it assumes the objects really do stand "
                "clear of the background. On a surface with a gradual slope, "
                "or where features merge into the substrate, the mask will cut "
                "through them.\n\n"
                "The setting runs the opposite way to what the name suggests, "
                "which was measured rather than assumed: on one scan 0.20 "
                "marked 86% of the frame, 0.35 marked 79%, 0.65 marked 28% "
                "and 0.80 marked 6%. At the old 0.35 the background fit had "
                "only a fifth of the image left to sit on, and levelling "
                "around the object came out worse than not masking at all.",
        creates_mask=True,
        settings={
            "/module/grain_mark/isheight": True,
            "/module/grain_mark/isslope": False,
            "/module/grain_mark/islap": False,
            "/module/grain_mark/isrank": False,
            # Chosen so the marked area lands near what this project's own
            # object detector finds -- about a fifth of the frame on the scan
            # this was calibrated against, rather than four fifths.
            "/module/grain_mark/height": 0.70,
            "/module/grain_mark/inverted": False,
            "/module/grain_mark/combine": False,
            "/module/grain_mark/merge_type": 0,
            "/module/grain_mark/update": True,
        },
    ),
    Operation(
        key="drop_small_marks",
        gwy_func="grain_filter",
        title="Discard the specks",
        menu="/Grains/Filter",
        what="Removes the smallest marked regions, keeping only objects of a "
             "meaningful size.",
        why="Thresholding always catches a scattering of single-pixel noise "
            "along with the real objects. Leaving those in the mask punches "
            "small holes in the background fit for no reason.",
        caution="Uses whatever size limit Gwyddion currently has set. If your "
                "objects are genuinely tiny, check that they survived.",
        needs_mask=True,
    ),
    Operation(
        key="background_around_objects",
        gwy_func="polylevel",
        title="Correct the background, ignoring the marked objects",
        menu="/Level/Polynomial Background",
        what="Fits a curved surface to the background only — every marked "
             "pixel is left out of the fit — and subtracts it from the whole "
             "image.",
        why="This is the answer to the usual complaint that a polynomial "
            "background 'acts on the whole image'. It does subtract from the "
            "whole image, which is correct, but with a mask it is *fitted* on "
            "the background alone. Measured on a test surface with a flat "
            "object on a curved base: fitting through everything left the "
            "object distorted by 8.4 nm, fitting around the mask left it flat "
            "to 0.3 nm.",
        caution="Still a polynomial, so it removes real long-wavelength "
                "structure along with the bow. Use the lowest order that "
                "flattens the background.",
        needs_mask=True,
        settings={
            "/module/polylevel/col_degree": 2,
            "/module/polylevel/row_degree": 2,
            "/module/polylevel/same_degree": True,
            "/module/polylevel/independent": 1,
            "/module/polylevel/do_extract": False,
            # 0 is MASK_EXCLUDE: the marked pixels take no part in the fit.
            "/module/polylevel/masking": 0,
        },
    ),
    Operation(
        key="plane_around_objects",
        gwy_func="polylevel",
        title="Level the background, ignoring the marked objects",
        menu="/Level/Polynomial Background",
        what="Fits a plane to the background only — every marked pixel is left "
             "out — and subtracts it from the whole image.",
        why="The same idea as the curved version, at the order a flat "
            "background actually needs. Both failures it sits between are "
            "real: level a scan with a tall object still in the fit and the "
            "object tilts the plane towards itself, leaving the base sloped, "
            "which the user reports as the commonest and hardest fault; fit a "
            "second-order surface to a background that has no curvature and it "
            "invents some at the corners.",
        caution="If the background genuinely bows, this leaves the bow. The "
                "order comes from what was measured, not from the recipe.",
        needs_mask=True,
        settings={
            "/module/polylevel/col_degree": 1,
            "/module/polylevel/row_degree": 1,
            "/module/polylevel/same_degree": True,
            "/module/polylevel/independent": 1,
            "/module/polylevel/do_extract": False,
            # 0 is MASK_EXCLUDE: the marked pixels take no part in the fit.
            "/module/polylevel/masking": 0,
        },
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
