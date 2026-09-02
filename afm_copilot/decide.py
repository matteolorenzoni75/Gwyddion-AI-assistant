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

# Below this fraction of the frame, what was marked is specks rather than
# objects, and masking them only punches holes in the background fit.
MIN_OBJECT_FRACTION = 0.03

# Objects are taken as the pixels this far above the background, as a fraction
# of the height range. Deliberately generous: a mask that is slightly too big
# costs a little background to fit on, one that is too small lets the object
# into the fit, which is the failure that matters.
OBJECT_THRESHOLD = 0.30


@dataclass
class Plan:
    """What to do to one scan, and the measurements behind it."""

    background_degree: int
    has_objects: bool
    object_fraction: float
    tilt: float
    explained_by_degree: dict[int, float] = field(default_factory=dict)
    already_levelled: bool = False
    notes: list[str] = field(default_factory=list)
    recipe_key: str = "level-only"

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


def detect_objects(data: np.ndarray,
                   threshold: float = OBJECT_THRESHOLD) -> np.ndarray:
    """
    Pixels standing clear of the background.

    Measured against the median rather than the mean, so a large object does
    not drag the reference up and hide itself.

    Known limit: once objects cover more than about half the frame the median
    sits inside them, and nothing is reported as standing clear. That is the
    honest answer -- with no majority background there is nothing to fit a
    background on -- but it means "no objects found" can mean either "a bare
    surface" or "almost entirely object".
    """
    data = np.asarray(data, dtype=float)
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros(data.shape, dtype=bool)
    base = float(np.median(finite))
    span = float(finite.max() - finite.min())
    if span <= 0:
        return np.zeros(data.shape, dtype=bool)
    return np.nan_to_num(data, nan=base) > base + threshold * span


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


def _find_objects_above_background(data: np.ndarray,
                                   passes: int = 2) -> np.ndarray:
    """
    Objects, found in the surface once its background is out of the way.

    Iterated, because the two depend on each other: a good background fit needs
    the objects excluded, and finding the objects needs the background gone.
    Two passes settle it -- the first removes enough tilt and bow for the
    objects to stand out, the second refits the background without them.

    Without this, a bowed surface has its raised rim marked as objects, and the
    background is then fitted around the very shape it was meant to remove.
    """
    mask = np.zeros(data.shape, dtype=bool)
    for _ in range(max(1, passes)):
        degree, _ = choose_background_degree(data, mask if mask.any() else None)
        residual = _subtract_background(data, degree,
                                        mask if mask.any() else None)
        mask = detect_objects(residual)
    return mask


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
    """
    explained = {d: background_explains(data, d, mask)
                 for d in range(max_degree + 1)}

    # A real background settles: the next order finds nothing more of that
    # shape. Take the lowest order that both explains something and settles.
    for degree in range(1, max_degree):
        if explained[degree] < MEANINGFUL_BACKGROUND:
            continue
        if explained[degree + 1] - explained[degree] < SETTLED:
            return degree, explained

    # Nothing settled: every order kept finding more, which means it is finding
    # the surface rather than a background. A plane is still defensible because
    # tilt is a real acquisition artifact with a physical cause; higher orders
    # here would be carving into the sample.
    if explained[1] >= MEANINGFUL_BACKGROUND:
        return 1, explained
    return 0, explained


def plan_for(channel: Channel) -> Plan:
    """Measure a scan and say what it needs, with the numbers."""
    from afm_copilot.analysis import plane_fraction

    data = np.asarray(channel.data, dtype=float)
    tilt = plane_fraction(data)

    # Objects stand above the *background*, not above the raw surface. Looking
    # for them before removing the background finds the high side of a tilt and
    # the rim of a bowl, neither of which is an object. So: rough background
    # out, find the objects in what is left, then choose the real background
    # with those excluded, and look once more.
    objects = _find_objects_above_background(data)
    fraction = float(objects.mean())
    # Below the lower bound there is nothing worth protecting; above the upper
    # one there is too little background left to fit anything on.
    has_objects = MIN_OBJECT_FRACTION < fraction < 0.60

    mask = objects if has_objects else None
    degree, explained = choose_background_degree(data, mask)

    plan = Plan(
        background_degree=degree,
        has_objects=has_objects,
        object_fraction=fraction,
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
        plan.notes.append(
            f"{fraction * 100:.0f}% of the frame stands clear of the "
            f"background — objects on a surface. The background can be "
            f"corrected around them, leaving them untouched by the fit.")
    elif fraction >= 0.60:
        plan.notes.append(
            f"{fraction * 100:.0f}% of the frame sits above the median, so "
            f"there is no distinct background to fit on. Treating this as "
            f"objects-on-a-surface would be wrong.")
    else:
        plan.notes.append(
            "Nothing stands clear of the surface — no separate objects to "
            "protect from the fit.")

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

    plan.recipe_key = _recipe_for_plan(plan)
    return plan


def _recipe_for_plan(plan: Plan) -> str:
    """Which of the written recipes matches what was measured."""
    if plan.has_objects and plan.background_degree > 0:
        return "isolate-objects"
    if plan.has_objects:
        # Objects present but a flat background: nothing to fit around them,
        # so the routine tidy-up is enough and safer.
        return "quick-clean"
    if plan.already_levelled and plan.background_degree == 0:
        return "level-only"
    return "quick-clean"
