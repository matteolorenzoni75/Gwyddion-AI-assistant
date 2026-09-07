"""
Decide what a scan needs, from the scan.

The alternative — a recipe chosen in advance, or by eye one scan at a time — has
already failed twice in this project: once by flattening a real feature and
reporting a 35% improvement, once by fitting curvature into a background that
had none. Both mistakes were invisible in the numbers and obvious in the image.

So the decisions here are made by measuring, and every one is returned with the
measurement that produced it. Nothing chooses silently.

The bias throughout is toward doing less. Every fitted parameter removes some
real roughness along with the artifact, and the error grows with the number of
parameters, so a correction has to earn its place: an order is only used if
dropping it leaves visible curvature behind.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import math

import numpy as np

from afm_copilot.gwy_io import Channel

# Below this, a scan's height variation contains no plane worth removing.
# A genuinely raw scan essentially never reads this low -- the instrument's own
# software has already levelled anything that does.
FLAT_ENOUGH = 0.02

# A fitted background has to account for at least this much of the height
# variation to be worth removing at all.
MEANINGFUL_BACKGROUND = 0.10

# A real background *settles*: raise the order and it explains no more, because
# there is nothing left of that shape to find. Fitting real surface structure
# instead keeps climbing, order after order. Measured across synthetic surfaces
# with known answers and the six real scans:
#
#   surface              order 1   order 2   order 3
#   ------------------   -------   -------   -------
#   synthetic tilt         99.9%     99.9%     99.9%   settles -> order 1
#   synthetic bowl          0.0%     99.1%     99.1%   settles -> order 2
#   real, tilted DVD       58.6%     58.8%     59.1%   settles -> order 1
#   real, already level     0.0%     46.3%     64.9%   never settles -> none
#
# The last row is the case that matters: a scan the instrument had already
# levelled, where every extra order kept finding something. What it was finding
# was the surface itself.
SETTLED = 0.05

# The same idea, measured against what is still unexplained rather than against
# the whole. The next order has to account for less than this share of the
# remainder for the background to count as settled. Judged absolutely, the test
# went blind on every scan whose background was already nearly perfect.
SETTLED_RELATIVE = 0.15

# An order of 2 or more has to account for at least this much before it is
# accepted in the loop. Tilt has a physical cause; curvature is as often the
# sample's own shape, and a second-order fit that explains 41% of a frame with
# three large domes in it would be carving the domes.
CURVATURE_MUST_EXPLAIN = 0.60

# When nothing settles, an order that accounts for this much of the height
# variation is a background anyway. Below it, the polynomial is tracking the
# surface rather than anything the instrument added.
BACKGROUND_DOMINATES = 0.80

# Below this fraction of the frame, what was marked is specks rather than
# objects, and masking them only punches holes in the background fit.
MIN_OBJECT_FRACTION = 0.03

# Rows out of line, or offset from each other, past which a scan needs its
# lines straightened whatever else is done to it. Below these the most
# conservative recipe is still defensible.
ROWS_NEED_ALIGNING = 0.01
BANDING_NEEDS_ALIGNING = 0.08

# The sequence of row medians has to let go of itself before it can be said to
# come back: it must fall below the first figure, then rise above the second.
ROWS_MUST_FALL_TO = 0.10
ROWS_REPEAT = 0.45

# Objects are taken as the pixels this far above the background, as a fraction
# of the height range. Deliberately generous: a mask that is slightly too big
# costs a little background to fit on, one that is too small lets the object
# into the fit, which is the failure that matters.
OBJECT_THRESHOLD = 0.30

# And however small that fraction turns out to be, a feature has to clear the
# noise by this much to count. A polished substrate has no features and a tiny
# height range, so a purely proportional threshold lands inside its noise and
# reports a fifth of the frame as objects.
MIN_SIGNAL_TO_NOISE = 4.0

# One connected piece larger than this much of the frame is not an object; it
# is background the fit did not remove. See _compact_only.
MAX_FEATURE_FRACTION = 0.20


@dataclass
class Plan:
    """What to do to one scan, and the measurements behind it."""

    background_degree: int
    has_objects: bool
    object_fraction: float
    raised_fraction: float = 0.0
    sunken_fraction: float = 0.0
    spike_fraction: float = 0.0
    needs_despike: bool = False
    stepped_rows: float = 0.0
    banding: float = 0.0
    tilt: float = 0.0

    rows_are_structure: bool = False
    columns: int = 0

    @property
    def banding_floor(self) -> float:
        """
        How much row-to-row scatter noise alone produces.

        A row's median of `n` independent values wanders by about 1.25/sqrt(n)
        of the surface's own spread, so a fixed threshold is a threshold on the
        image width. At 256 columns that floor is 0.078 -- which is where the
        fixed 0.08 sat, so pure noise was being sent off to have its rows
        straightened.
        """
        if self.columns <= 1:
            return BANDING_NEEDS_ALIGNING
        return max(BANDING_NEEDS_ALIGNING,
                   2.5 * 1.25 / math.sqrt(self.columns))

    @property
    def line_defects(self) -> bool:
        """
        Rows that need straightening before anything else is believed.

        Not when the row-to-row variation is the sample. Aligning rows works on
        the slow axis, so a pattern that varies along it lives in exactly the
        row medians the correction removes: a honeycomb lost a quarter of its
        periodicity that way and came back wavy, while a grating of vertical
        stripes -- whose row medians are all alike -- passed through untouched.
        """
        if self.rows_are_structure:
            return False
        return (self.stepped_rows >= ROWS_NEED_ALIGNING
                or self.banding >= self.banding_floor)
    explained_by_degree: dict[int, float] = field(default_factory=dict)
    already_levelled: bool = False
    notes: list[str] = field(default_factory=list)
    recipe_key: str = "level-only"
    # The surface this plan was decided on, so the stages after it can use the
    # same one rather than each fitting its own background.
    levelling: "Levelling | None" = None

    def explain(self) -> str:
        lines = [f"Recommended: {self.recipe_key}", ""]
        lines.extend(f"  {n}" for n in self.notes)
        if self.explained_by_degree:
            lines.append("")
            lines.append("  How much of the height variation a background of "
                         "each order accounts for:")
            for degree, share in sorted(self.explained_by_degree.items()):
                settled = ""
                nxt = self.explained_by_degree.get(degree + 1)
                if nxt is not None and nxt - share < SETTLED and share > 0:
                    settled = "   (settles here)"
                lines.append(f"      order {degree}: {share * 100:5.1f}%{settled}")
        return "\n".join(lines)


def _design(shape: tuple[int, int], degree: int) -> np.ndarray:
    """
    Columns of x^i * y^j for every term up to the given total degree.

    Coordinates run -1..1 so the columns stay comparable in size and the fit
    does not become ill-conditioned at higher orders.
    """
    h, w = shape
    y, x = np.mgrid[0:h, 0:w].astype(float)
    x = 2.0 * x / max(1, w - 1) - 1.0
    y = 2.0 * y / max(1, h - 1) - 1.0
    columns = [(x ** i) * (y ** j)
               for total in range(degree + 1)
               for i in range(total + 1)
               for j in [total - i]]
    return np.column_stack([c.ravel() for c in columns])


def background_explains(data: np.ndarray, degree: int,
                        mask: np.ndarray | None = None) -> float:
    """
    The fraction of the height variation a fitted background of this order
    accounts for.

    Fitted only where `mask` is False, so the objects take no part in deciding
    what the background is.

    This is measured rather than the leftover residual because the residual
    cannot tell the two failure modes apart: removing a real background and
    carving into real structure both make it smaller.
    """
    data = np.asarray(data, dtype=float)
    usable = np.isfinite(data)
    if mask is not None:
        usable &= ~mask
    if usable.sum() < (degree + 1) * (degree + 2):
        return 0.0

    design = _design(data.shape, degree)
    flat = usable.ravel()
    values = data.ravel()[flat]
    total = float(np.var(values))
    if total <= 0:
        return 0.0
    try:
        coef, *_ = np.linalg.lstsq(design[flat], values, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0
    return float(np.var(design[flat] @ coef) / total)


def residual_after_background(data: np.ndarray, degree: int,
                              mask: np.ndarray | None = None) -> float:
    """How much height variation is left once a background of this order is gone."""
    data = np.asarray(data, dtype=float)
    usable = np.isfinite(data)
    if mask is not None:
        usable &= ~mask
    if usable.sum() < (degree + 1) * (degree + 2):
        return float(np.nanstd(data))

    design = _design(data.shape, degree)
    flat = usable.ravel()
    try:
        coef, *_ = np.linalg.lstsq(design[flat], data.ravel()[flat], rcond=None)
    except np.linalg.LinAlgError:
        return float(np.nanstd(data[usable]))
    residual = data.ravel()[flat] - design[flat] @ coef
    return float(np.std(residual))


def detect_features(data: np.ndarray,
                    threshold: float = OBJECT_THRESHOLD,
                    ) -> tuple[np.ndarray, np.ndarray]:
    """
    What stands clear of the background -- upwards and downwards.

    Both directions, because a surface can be interesting for what is missing
    from it as much as for what sits on it. Looking only upwards made a porous
    surface and a perfectly smooth one identical: on three pitted scans of the
    test pool the count reported zero objects against dozens of obvious holes,
    while the height asymmetry separated them without effort (-1.97, -1.51,
    -1.89 against +1.43 for grains sitting on top).

    Measured against the median rather than the mean, so a large feature does
    not drag the reference towards itself and hide.

    A feature must also stand clear of the *noise*, not merely of a fraction of
    the height range. Without that, a polished substrate whose whole variation
    is a few nanometres has 18% of its frame declared "objects" -- the
    threshold working inside the noise floor and finding nothing but itself.

    Three limits, all measured, none of them hidden:

    * Once features cover more than about half the frame the median sits inside
      them and little is reported. With no majority background there is nothing
      to stand clear of. A close-packed layer of spheres therefore comes back
      reporting the *gaps between* them, which describes the sample backwards
      -- so `object_polarity` is the number to distrust there, not the count.
    * A background the fit did not fully remove can still be found. On a
      polished substrate an order-1 fit leaves an 18 nm bow on a surface whose
      noise is 0.7 nm, and the top of that bow is reported as raised features
      covering a fifth of the frame. The cure is a better background, not a
      stricter threshold.
    * Row banding swamps everything on a very flat surface: 0.9 nm of mica
      under 0.9 of banding reports nothing at all until the rows are aligned.
    """
    from afm_copilot.quality import noise_level

    data = np.asarray(data, dtype=float)
    empty = np.zeros(data.shape, dtype=bool)
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return empty, empty.copy()

    base = float(np.median(finite))
    span = float(finite.max() - finite.min())
    if span <= 0:
        return empty, empty.copy()

    clearance = max(threshold * span, MIN_SIGNAL_TO_NOISE * noise_level(data))
    filled = np.nan_to_num(data, nan=base)
    return (_compact_only(filled > base + clearance),
            _compact_only(filled < base - clearance))

# Comparing each pixel to a local baseline instead of the global median was
# tried here and reverted. It did reduce the polished-substrate false positive
# from 19.7% to 1.9%, and in exchange it lost the close-packed spheres
# entirely, halved the pits found on the porous scans, and broke the masked
# background fit on a bowed surface. One case better, three worse: not a
# trade worth taking. The two limitations below are documented instead.


def _compact_only(mask: np.ndarray) -> np.ndarray:
    """
    Drop anything too large to be an object.

    A feature is compact; a background is not. When a fitted background leaves
    a gentle ramp behind, the high end of that ramp clears any threshold and
    arrives as one enormous blob -- which is how two polished substrates came
    to have a fifth of their frame reported as objects, on surfaces with
    nothing on them at all.

    Size is the honest discriminator here rather than height: the leftover
    ramp is as tall as a real object would be, and only its extent gives it
    away. Anything covering more than a fifth of the frame in one connected
    piece is background that was not fully removed, and masking it would
    starve the next background fit of the very area it needs.
    """
    if not mask.any():
        return mask
    from scipy import ndimage

    labels, count = ndimage.label(mask)
    if count == 0:
        return mask
    areas = np.bincount(labels.ravel())
    too_big = np.flatnonzero(areas > MAX_FEATURE_FRACTION * mask.size)
    if too_big.size == 0 or (too_big.size == 1 and too_big[0] == 0):
        return mask
    return mask & ~np.isin(labels, too_big[too_big > 0])


def detect_objects(data: np.ndarray,
                   threshold: float = OBJECT_THRESHOLD) -> np.ndarray:
    """
    Everything that is not background, whichever way it departs from it.

    This is the mask a background fit needs: a pit distorts a fitted surface
    exactly as a bump does, and leaving one in while excluding the other is
    half a correction.
    """
    above, below = detect_features(data, threshold)
    return above | below


def _subtract_background(data: np.ndarray, degree: int,
                         mask: np.ndarray | None = None) -> np.ndarray:
    """The surface with a fitted background removed."""
    usable = np.isfinite(data)
    if mask is not None:
        usable &= ~mask
    if usable.sum() < (degree + 1) * (degree + 2):
        return data
    design = _design(data.shape, degree)
    flat = usable.ravel()
    try:
        coef, *_ = np.linalg.lstsq(design[flat], data.ravel()[flat], rcond=None)
    except np.linalg.LinAlgError:
        return data
    return data - (design @ coef).reshape(data.shape)


def _find_features(data: np.ndarray,
                   passes: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """
    What departs from the surface, once its background is out of the way.

    Returns the raised and the sunken parts separately, because which of the
    two a surface has is most of what distinguishes one kind of sample from
    another -- grains sitting on a substrate against pores eaten into a film.

    Iterated, because the two depend on each other: a good background fit needs
    the features excluded, and finding the features needs the background gone.
    Two passes settle it -- the first removes enough tilt and bow for them to
    stand out, the second refits the background without them.

    Without this, a bowed surface has its raised rim marked as objects, and the
    background is then fitted around the very shape it was meant to remove.
    """
    mask = np.zeros(data.shape, dtype=bool)
    above = below = mask
    for _ in range(max(1, passes)):
        degree, _ = choose_background_degree(data, mask if mask.any() else None)
        residual = _subtract_background(data, degree,
                                        mask if mask.any() else None)
        above, below = detect_features(residual)
        mask = above | below
    return above, below


@dataclass
class Levelling:
    """
    One scan's background, chosen once and shared.

    Every stage needs the surface with its background removed -- deciding what
    to do, measuring, judging quality, bounding the tip -- and each was working
    it out for itself. On a 512-square scan that meant the background chosen
    five times and fitted twenty, about two thirds of the batch's whole running
    time, and four subtly different levelled surfaces describing one image.

    The cost was the obvious half. The other half is that the numbers reported
    for a scan should describe the same surface as the picture drawn of it.
    """

    degree: int
    explained: dict[int, float]
    flat: np.ndarray


def level(data: np.ndarray, mask: np.ndarray | None = None) -> Levelling:
    """Choose the background order once, and keep the surface it leaves."""
    degree, explained = choose_background_degree(data, mask)
    return Levelling(degree=degree, explained=explained,
                     flat=_subtract_background(data, max(1, degree), mask))


def choose_background_degree(
    data: np.ndarray,
    mask: np.ndarray | None = None,
    max_degree: int = 3,
) -> tuple[int, dict[int, float]]:
    """
    The lowest polynomial order that actually flattens the background.

    Each order is kept only if it cuts the leftover curvature by an appreciable
    fraction. Otherwise the fit is spending real roughness to chase noise --
    which is how a second-order background came to be fitted to a surface that
    was already flat.

    "Appreciable" means appreciable **against what is left**, not against the
    whole. Measured absolutely, the rule was blind wherever a background was
    nearly perfect already: on a polished substrate an order-1 fit explained
    99.59% and order 2 explained 99.95%, so the extra 0.36% looked negligible
    and order 1 was chosen -- leaving an 18 nm bow on a surface whose noise is
    0.7 nm. That 0.36% was 88% of everything still unexplained.
    """
    explained = {d: background_explains(data, d, mask)
                 for d in range(max_degree + 1)}

    # A real background settles: the next order finds almost nothing more of
    # that shape, relative to what remains. Take the lowest order that does.
    for degree in range(1, max_degree):
        if explained[degree] < MEANINGFUL_BACKGROUND:
            continue
        # Curvature has to earn more than tilt does. A tilted sample has a
        # physical cause -- how it sits on the stage -- while curvature is as
        # likely to be the shape of the sample itself, and removing it would be
        # carving into what we are trying to measure.
        if degree >= 2 and explained[degree] < CURVATURE_MUST_EXPLAIN:
            continue
        remaining = 1.0 - explained[degree]
        gain = explained[degree + 1] - explained[degree]
        if remaining <= 0 or gain / remaining < SETTLED_RELATIVE:
            return degree, explained

    # Nothing settled: every order kept finding more, which means it is finding
    # the surface rather than a background.
    #
    # One exception, and it is what separates the two cases that look alike
    # here. When a low order already accounts for the great majority of the
    # height variation, it *is* the background whether or not the next order
    # keeps improving on it -- flakes on mica, where order 2 explained 88%
    # against order 1's 34%. When no order reaches that, the polynomial is
    # tracking the surface: a scan the instrument had already levelled climbed
    # 0%, 46%, 65% order after order, and every one of those orders was the
    # sample.
    for degree in range(1, max_degree + 1):
        if explained[degree] >= BACKGROUND_DOMINATES:
            return degree, explained

    # Otherwise a plane is still defensible, because tilt is a real acquisition
    # artifact; higher orders here would be carving into the sample.
    if explained[1] >= MEANINGFUL_BACKGROUND:
        return 1, explained
    return 0, explained


def plan_for(channel: Channel) -> Plan:
    """
    Measure a scan and say what it needs, with the numbers.

    The levelling it settles on is carried on the returned Plan, so the stages
    that follow describe the same surface instead of each working out its own.
    """
    from afm_copilot.analysis import plane_fraction

    data = np.asarray(channel.data, dtype=float)
    tilt = plane_fraction(data)

    # Objects stand above the *background*, not above the raw surface. Looking
    # for them before removing the background finds the high side of a tilt and
    # the rim of a bowl, neither of which is an object. So: rough background
    # out, find the objects in what is left, then choose the real background
    # with those excluded, and look once more.
    above, below = _find_features(data)
    objects = above | below
    fraction = float(objects.mean())
    raised, sunken = float(above.mean()), float(below.mean())
    # Below the lower bound there is nothing worth protecting; above the upper
    # one there is too little background left to fit anything on.
    has_objects = MIN_OBJECT_FRACTION < fraction < 0.60

    mask = objects if has_objects else None
    settled = level(data, mask)
    degree, explained = settled.degree, settled.explained

    from afm_copilot.features import row_banding, row_step_fraction
    from afm_copilot.quality import SPIKES_WORTH_REPAIRING, spike_fraction

    spikes = spike_fraction(data)
    levelled = settled.flat

    plan = Plan(
        stepped_rows=row_step_fraction(levelled),
        banding=row_banding(levelled),
        rows_are_structure=rows_carry_structure(levelled),
        columns=int(data.shape[1]),
        background_degree=degree,
        has_objects=has_objects,
        object_fraction=fraction,
        raised_fraction=raised,
        sunken_fraction=sunken,
        spike_fraction=spikes,
        needs_despike=spikes >= SPIKES_WORTH_REPAIRING,
        tilt=tilt,
        explained_by_degree=explained,
        already_levelled=tilt < FLAT_ENOUGH,
    )

    if plan.already_levelled:
        plan.notes.append(
            f"A plane accounts for only {tilt * 100:.0f}% of the height "
            f"variation, so this scan arrived already levelled — the "
            f"instrument's own software had done it.")
    else:
        plan.notes.append(
            f"A plane accounts for {tilt * 100:.0f}% of the height variation, "
            f"so there is real tilt to remove.")

    if has_objects:
        # Which way they depart matters more than how many there are: the same
        # count means grains on a substrate or pores in a film, and those are
        # not the same sample.
        if sunken > 2 * raised:
            what = (f"{sunken * 100:.0f}% of the frame lies *below* the "
                    f"surface — holes or pores rather than objects sitting on "
                    f"it")
        elif raised > 2 * sunken:
            what = (f"{raised * 100:.0f}% of the frame stands *above* the "
                    f"surface — objects sitting on it")
        else:
            what = (f"{fraction * 100:.0f}% of the frame departs from the "
                    f"surface, about equally up and down — a texture rather "
                    f"than objects on a background")
        plan.notes.append(
            what + ". The background can be corrected around it, leaving it "
            "untouched by the fit.")
    elif fraction >= 0.60:
        plan.notes.append(
            f"{fraction * 100:.0f}% of the frame sits above the median, so "
            f"there is no distinct background to fit on. Treating this as "
            f"objects-on-a-surface would be wrong.")
    else:
        plan.notes.append(
            "Nothing stands clear of the surface, in either direction — no "
            "separate features to protect from the fit.")

    if plan.rows_are_structure:
        plan.notes.append(
            "The row-to-row variation repeats, so it is the sample and not an "
            "offset — this surface has structure running along the slow scan "
            "axis. Nothing that aligns rows will touch it: doing so erases the "
            "pattern and leaves waviness where it was.")
    elif plan.line_defects:
        plan.notes.append(
            f"{plan.stepped_rows:.0%} of the rows step away from their "
            f"neighbours (offset {plan.banding:.2f} of the surface's own "
            f"variation), so the lines are straightened and the strokes "
            f"repaired — a scar dragged along the fast axis is the tip losing "
            f"and regaining the surface, never the sample.")

    if spikes > 0.005:
        plan.notes.append(
            f"{spikes:.1%} of the frame departs sharply from its neighbours. "
            f"That can be dropouts, dust or glitches — or small tall features "
            f"that are entirely real, and nothing measurable here tells the "
            f"two apart. Nothing is repaired on this number alone; use "
            f"`--despike` if you know the sample has no such features.")

    if degree == 0:
        plan.notes.append(
            "The background needs no curvature removed: a higher order does "
            "not flatten it further, and fitting one anyway would remove real "
            "structure.")
    else:
        plan.notes.append(
            f"An order-{degree} background accounts for "
            f"{explained[degree] * 100:.0f}% of the height variation, and a "
            f"higher order finds no more of that shape — so it is a real "
            f"background rather than the surface itself.")

    plan.levelling = settled
    plan.recipe_key = _recipe_for_plan(plan)
    return plan


def rows_carry_structure(flat: np.ndarray,
                         min_repeats: float = 3.0) -> bool:
    """
    Are the row-to-row differences the sample, or the instrument?

    Row alignment removes whatever the median of each row says, so it is safe
    exactly when those medians carry no information -- offsets from a drifting
    feedback, which wander at random. When the sample itself varies along the
    slow axis the medians follow it, and straightening them erases the pattern
    and leaves waviness where it was.

    The test is whether the sequence of row medians *repeats*. A random walk
    does not; a surface with horizontal or diagonal structure does. Vertical
    stripes give identical medians and so never trip this, which is why a
    calibration grating survives row alignment untouched while a honeycomb
    does not.
    """
    rows = np.nanmedian(np.asarray(flat, dtype=float), axis=1)
    rows = rows[np.isfinite(rows)]
    if rows.size < 32:
        return False
    rows = rows - rows.mean()
    spread = float(np.std(rows))
    if spread <= 0:
        return False

    # Autocorrelation of the row-median sequence -- and what matters is not how
    # high it stays but whether it *comes back*. Any smooth surface has row
    # medians that resemble themselves a few rows later, so a plain threshold
    # fired on 94% of the batch. A repeat is a sequence that falls away and
    # then rises again; a wandering offset falls and stays down.
    correlation = np.correlate(rows, rows, mode="full")[rows.size - 1:]
    correlation = correlation / correlation[0]
    longest = int(rows.size / min_repeats)
    if longest <= 6:
        return False

    dip = None
    for lag in range(2, longest):
        if correlation[lag] < ROWS_MUST_FALL_TO:
            dip = lag
            break
    if dip is None:
        return False                     # never let go: smooth, not periodic

    rebound = correlation[dip:longest]
    return bool(rebound.size and rebound.max() >= ROWS_REPEAT)


def _recipe_for_plan(plan: Plan) -> str:
    """Which of the written recipes matches what was measured."""
    if plan.rows_are_structure:
        # Nothing that aligns rows may touch this scan: the row medians are
        # the sample. 'Roughness ready' is the recipe that levels and repairs
        # scars without going near them -- it exists because row-wise
        # correction biases roughness, and the same property protects a
        # pattern that varies along the slow axis.
        return "roughness-ready"
    if plan.has_objects and plan.background_degree > 0:
        return "isolate-objects"
    if plan.has_objects:
        # Objects present but a flat background: nothing to fit around them,
        # so the routine tidy-up is enough and safer.
        return "quick-clean"
    if plan.already_levelled and plan.background_degree == 0:
        # Unless the lines are damaged. 'Level only' says so in its own words
        # -- do not use it when the image has obvious banding or scars, it will
        # not touch them -- and nothing was checking: 23 of the 30 scans routed
        # here in one batch had rows out of line, the worst of them 45%, and
        # every one came out with the damage untouched.
        if plan.line_defects:
            return "quick-clean"
        return "level-only"
    return "quick-clean"
