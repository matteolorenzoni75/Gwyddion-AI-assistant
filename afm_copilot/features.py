"""
Everything measurable about a scan, in one place.

Two different questions need the same numbers: *what should be done to this
scan* (decide.py) and *what kind of surface is this* (recognition). Keeping the
measurements in one module means those two never drift apart, and a
measurement improved for one improves the other.

Every value here is computed from the pixels. Nothing reads a filename, and
nothing consults a list of known samples. That is deliberate: the test set is
kept blind on purpose, and a descriptor that peeks is worthless for judging
whether the recognition actually works.

The groups are:

    form        tilt and background order -- the shape the instrument added
    lines       banding between scan rows, and single bad rows
    objects     what stands above the surface, and its size distribution
    periodic    repeating structure, its direction and its wavelength
    texture     roughness, correlation length, and the shape of the height
                distribution
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

from afm_copilot.gwy_io import Channel


# --------------------------------------------------------------------------
# form
# --------------------------------------------------------------------------

def _design(shape: tuple[int, int], degree: int) -> np.ndarray:
    """Polynomial terms up to a total degree, on coordinates running -1..1."""
    h, w = shape
    y, x = np.mgrid[0:h, 0:w].astype(float)
    x = 2.0 * x / max(1, w - 1) - 1.0
    y = 2.0 * y / max(1, h - 1) - 1.0
    return np.column_stack([((x ** i) * (y ** j)).ravel()
                            for total in range(degree + 1)
                            for i in range(total + 1)
                            for j in [total - i]])


def background_explains(data: np.ndarray, degree: int,
                        mask: np.ndarray | None = None) -> float:
    """Fraction of the height variation a fitted background of this order takes."""
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


def subtract_background(data: np.ndarray, degree: int,
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


# --------------------------------------------------------------------------
# lines
# --------------------------------------------------------------------------

def row_banding(data: np.ndarray) -> float:
    """
    How much of the height variation is whole rows sitting at wrong heights.

    Scan lines drift in z between one another, which shows as horizontal
    banding. Measured as the share of the variance carried by the row means
    once the row-to-row *trend* is gone -- otherwise a plain tilt along the
    slow axis would read as banding, which it is not.
    """
    rows = np.nanmean(data, axis=1)
    if rows.size < 8:
        return 0.0
    total = float(np.nanvar(data))
    if total <= 0:
        return 0.0
    # Remove a smooth trend down the slow axis; what is left is line-to-line.
    index = np.arange(rows.size, dtype=float)
    trend = np.polyval(np.polyfit(index, rows, 2), index)
    return float(np.nanvar(rows - trend) / total)


def row_step_fraction(data: np.ndarray, sigma: float = 3.0) -> float:
    """
    The share of rows that jump away from their neighbours.

    A single row displaced in z is a scan-line defect; a gradual drift is not.
    Measured on the differences between adjacent row medians.
    """
    medians = np.nanmedian(data, axis=1)
    if medians.size < 8:
        return 0.0
    steps = np.diff(medians)
    spread = np.nanmedian(np.abs(steps - np.nanmedian(steps)))
    if spread <= 0:
        return 0.0
    # 1.4826 makes the median absolute deviation comparable to a std.
    outliers = np.abs(steps - np.nanmedian(steps)) > sigma * 1.4826 * spread
    return float(outliers.mean())


# --------------------------------------------------------------------------
# objects
# --------------------------------------------------------------------------

# Finding what departs from the surface lives in `decide`, and used to live
# here as well -- two copies of the same idea, drifting apart. Re-exported so
# the callers and tests that reach for it here keep working.
from afm_copilot.decide import detect_features, detect_objects  # noqa: E402


def object_statistics(mask: np.ndarray, pixel_size: float) -> dict:
    """
    Count and size of the separate objects in a mask.

    Size is reported as an equivalent diameter in metres, which is comparable
    between scans of different pixel pitch -- unlike a pixel count.
    """
    from scipy import ndimage

    if not mask.any():
        return {"object_count": 0, "object_median_size": 0.0,
                "object_size_spread": 0.0, "object_elongation": 0.0}

    labels, count = ndimage.label(mask)
    if count == 0:
        return {"object_count": 0, "object_median_size": 0.0,
                "object_size_spread": 0.0, "object_elongation": 0.0}

    areas = np.bincount(labels.ravel())[1:]
    # Single pixels are noise, not objects.
    areas = areas[areas >= 4]
    if areas.size == 0:
        return {"object_count": 0, "object_median_size": 0.0,
                "object_size_spread": 0.0, "object_elongation": 0.0}

    diameters = 2.0 * np.sqrt(areas / math.pi) * pixel_size
    median = float(np.median(diameters))

    # Elongation separates rods from round particles: the mean ratio of an
    # object's bounding box sides.
    ratios = []
    for sl in ndimage.find_objects(labels):
        if sl is None:
            continue
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        if h * w >= 4:
            ratios.append(max(h, w) / max(1, min(h, w)))

    return {
        "object_count": int(areas.size),
        "object_median_size": median,
        "object_size_spread": float(np.std(diameters) / median) if median > 0 else 0.0,
        "object_elongation": float(np.median(ratios)) if ratios else 0.0,
    }


# --------------------------------------------------------------------------
# periodic structure
# --------------------------------------------------------------------------

# Nothing shorter than this can be called a structure: at two pixels an image
# is at its sampling limit and describes nothing at all. Four is the smallest
# spacing whose shape survives.
MIN_PERIOD_PIXELS = 4.0

# A repeat has to happen more than once to be a repeat. Below three cycles
# across the frame there is not enough evidence to tell a periodic surface from
# one broad feature.
MIN_PERIOD_REPEATS = 3.0

# How strongly the profile must oscillate: the correlation one period later
# minus the correlation half a period later. A clean grating reaches 2, a
# smooth surface with no repeat sits near 0. See _repeats_in_the_image.
MIN_PERIOD_AGREEMENT = 0.60

# Distinct candidate waves examined before giving up.
MAX_PERIOD_CANDIDATES = 24


def periodicity(data: np.ndarray, pixel_size: float,
                search_harder: bool = False) -> dict:
    """
    Repeating structure: how strong, which way, and at what spacing.

    Found in the 2D Fourier transform. A repeating surface puts its energy into
    a few sharp peaks; a random one spreads it. Strength is the highest peak
    measured against the local background of the spectrum, so it does not
    depend on how rough the surface is overall.

    The direction is the important part and the reason this is not simply a
    peak search: stripes at any angle must be found, not only those along the
    scan axes.
    """
    finite = np.isfinite(data)
    if finite.sum() < 64:
        return {"periodicity": 0.0, "period_angle": float("nan"),
                "period_length": float("nan")}

    field = np.nan_to_num(data - np.nanmean(data))
    h, w = field.shape
    # A window, or the image edges themselves produce a cross of false peaks.
    window = np.outer(np.hanning(h), np.hanning(w))
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(field * window)))

    cy, cx = h // 2, w // 2
    yy, xx = np.mgrid[0:h, 0:w]
    radius = np.hypot(yy - cy, xx - cx)

    # Ignore the centre (that is the overall form, not a repeat) and the
    # highest frequencies (that is pixel noise).
    usable = (radius > 3) & (radius < min(h, w) / 2 - 2)

    # And refuse periods shorter than a few pixels outright. A "period" of two
    # pixels is the physical limit below which an image describes nothing, and
    # it is where this measurement kept landing: on six scans of the test pool,
    # including the optical disc -- the most plainly periodic image in it --
    # the reported spacing was the sampling limit rather than the structure.
    frequency = np.hypot((yy - cy) / float(h), (xx - cx) / float(w))
    with np.errstate(divide="ignore"):
        period_px = np.where(frequency > 0, 1.0 / frequency, np.inf)
    usable &= period_px >= MIN_PERIOD_PIXELS

    if not usable.any():
        return {"periodicity": 0.0, "period_angle": float("nan"),
                "period_length": float("nan"), "period_confirmed": 0.0}

    # Compare each point to the other directions at the SAME spatial
    # frequency, not to the spectrum as a whole. Any natural surface has far
    # more energy at low frequencies than at high, so a global comparison makes
    # every rough surface look periodic -- the peak is simply the largest of
    # the low-frequency terms. What marks a repeating structure is energy
    # concentrated in one *direction* at a given spacing.
    rings = radius.astype(int)
    ring_median = np.zeros_like(spectrum)
    for r in range(int(rings[usable].min()), int(rings[usable].max()) + 1):
        band = usable & (rings == r)
        if band.sum() >= 8:
            ring_median[band] = np.median(spectrum[band])

    # Give the ring comparison a floor, taken from the outermost rings where
    # there is nothing but noise. Without it the division is unfair by
    # construction: a high-frequency ring holds almost no energy, so its median
    # is near zero and any noise pixel divided by it scores in the millions,
    # burying every real low-frequency peak in the ranking. With the floor a
    # noise pixel scores about 1, which is what it deserves.
    outer = usable & (radius > 0.6 * float(radius[usable].max()))
    noise_floor = float(np.median(spectrum[outer])) if outer.any() else 0.0
    if noise_floor > 0:
        ring_median = np.maximum(ring_median, noise_floor)

    significant = usable & (ring_median > 0)
    if not significant.any():
        return {"periodicity": 0.0, "period_angle": float("nan"),
                "period_length": float("nan"), "period_confirmed": 0.0}

    contrast = np.zeros_like(spectrum)
    contrast[significant] = spectrum[significant] / ring_median[significant]

    # The transform proposes; the image itself decides. Walk the candidate
    # peaks from strongest down and keep the first that survives a check in
    # real space -- see _repeats_in_the_image. Without this a single groove
    # crossing the frame scores 28 against the 3-4 of a random surface, because
    # one straight edge does resemble a stripe of very long wavelength.
    order = np.argsort(contrast, axis=None)[::-1]
    tested: list[tuple[int, int]] = []
    for flat_index in order[:MAX_PERIOD_CANDIDATES * 8]:
        py, px = np.unravel_index(int(flat_index), contrast.shape)
        if not significant[py, px]:
            continue
        dy, dx = py - cy, px - cx
        fy, fx = dy / float(h), dx / float(w)

        # One peak and its mirror describe the same wave; so do neighbouring
        # pixels of one broad peak. Test each distinct wave once.
        key = (int(round(fy * 40)), int(round(fx * 40)))
        if key in tested or (-key[0], -key[1]) in tested:
            continue
        tested.append(key)
        if len(tested) > MAX_PERIOD_CANDIDATES:
            break

        agreement = _repeats_in_the_image(field * window, fy, fx)
        if agreement < MIN_PERIOD_AGREEMENT:
            continue

        # The stripes run perpendicular to the direction of the peak.
        angle = math.degrees(math.atan2(dy, dx)) % 180.0
        freq = math.hypot(fy, fx)
        return {"periodicity": float(contrast[py, px]),
                "period_angle": (angle + 90.0) % 180.0,
                "period_length": (pixel_size / freq) if freq > 0 else float("nan"),
                "period_confirmed": agreement}

    # The transform found nothing it could stand behind. A direct sweep of real
    # space would find repeats the transform misses -- faint ones, curved ones,
    # ones that happen only three or four times across the frame. It is
    # deliberately **off** by default, and the reason is measured rather than
    # assumed: switched on, it costs more in false positives than it buys in
    # recall. It called two-pixel noise a structure at 1.89 out of 2, and gave
    # a 45 um frame a "period" of 17 um, which is 2.6 repeats.
    #
    # What it lacks is a way to tell a repeat from a disturbance, and that is
    # arriving: with the scan speed from the file, mains interference at 50 Hz
    # lands at a spacing we can compute exactly -- 3.744 um/s gives 74.9 nm,
    # and its harmonics at 37.4 and 25.0 nm -- always along the fast axis.
    # Every false candidate above sat in that family. Once the metadata
    # survives conversion, this becomes usable and the default can change.
    if not search_harder:
        return {"periodicity": 0.0, "period_angle": float("nan"),
                "period_length": float("nan"), "period_confirmed": 0.0}

    agreement, wave = _sweep_for_repeat(field * window)
    if agreement >= MIN_PERIOD_AGREEMENT and wave is not None:
        fy, fx = wave
        angle = math.degrees(math.atan2(fy * h, fx * w)) % 180.0
        freq = math.hypot(fy, fx)
        return {"periodicity": float(agreement),
                "period_angle": (angle + 90.0) % 180.0,
                "period_length": (pixel_size / freq) if freq > 0 else float("nan"),
                "period_confirmed": agreement,
                "period_found_by": "sweep"}

    # Nothing repeated. Reporting zero is the honest answer, and a great deal
    # better than the strongest noise peak dressed up as a structure.
    return {"periodicity": 0.0, "period_angle": float("nan"),
            "period_length": float("nan"), "period_confirmed": 0.0}


def _sweep_for_repeat(field: np.ndarray) -> tuple[float, tuple[float, float] | None]:
    """
    Look for a repeat by trying directions and spacings directly.

    Coarse first, then finer around whatever the coarse pass liked best, so the
    cost stays near two hundred projections rather than thousands. Slower than
    reading a peak off the transform and far more patient: it does not care
    whether the repeat is sharp, only whether it is there.
    """
    h, w = field.shape
    longest = min(h, w) / MIN_PERIOD_REPEATS
    if longest <= MIN_PERIOD_PIXELS:
        return 0.0, None

    def best_over(angles: np.ndarray, periods: np.ndarray):
        best, wave = 0.0, None
        for a in angles:
            sa, ca = math.sin(a), math.cos(a)
            for p in periods:
                candidate = (sa / p, ca / p)
                agree = _repeats_in_the_image(field, candidate[0], candidate[1])
                if agree > best:
                    best, wave = agree, candidate
        return best, wave

    coarse_angles = np.linspace(0.0, math.pi, 24, endpoint=False)
    coarse_periods = np.geomspace(MIN_PERIOD_PIXELS, longest, 18)
    best, wave = best_over(coarse_angles, coarse_periods)
    if wave is None:
        return 0.0, None

    # Refine: the coarse grid gives the neighbourhood, not the value.
    angle = math.atan2(wave[0], wave[1])
    period = 1.0 / math.hypot(*wave)
    fine_angles = np.linspace(angle - 0.13, angle + 0.13, 7)
    fine_periods = np.linspace(period * 0.8, period * 1.25, 11)
    # Clip at BOTH ends. Only clipping the short end let the refinement stretch
    # a period past the longest the frame can evidence, and a 45 um scan came
    # back with a 17 um "repeat" -- 2.6 of them across the whole image.
    fine_periods = fine_periods[(fine_periods >= MIN_PERIOD_PIXELS)
                                & (fine_periods <= longest)]
    if fine_periods.size:
        better, finer = best_over(fine_angles, fine_periods)
        if better > best:
            best, wave = better, finer
    return best, wave


def _repeats_in_the_image(field: np.ndarray, fy: float, fx: float,
                          bins_per_cycle: int = 8) -> float:
    """
    Does the candidate wave actually repeat in the surface, or only in the
    transform?

    Project every pixel onto the direction the wave travels and average the
    heights at each position along it. Then ask two questions of that profile,
    not one: does it resemble itself a **whole** period later, and does it
    resemble the *opposite* of itself **half** a period later.

    Both are needed, and the second is the one that does the work. Asking only
    the first rewards any smooth surface -- a gentle slope also looks like
    itself four pixels on, which is how an earlier version of this check passed
    a single step with 0.90 and read a 74-pixel grating as a 4-pixel one. What
    separates a genuine repeat is that it comes back *inverted* at half a
    period: a grating scores about +1 and -1, giving 2, while a smooth profile
    scores about +1 and +1, giving 0.

    Returns that difference, from 0 (no repeat) to 2 (a clean oscillation).
    """
    h, w = field.shape
    yy, xx = np.mgrid[0:h, 0:w]
    phase = xx * fx + yy * fy                       # position, in cycles
    span = float(phase.max() - phase.min())
    if span < MIN_PERIOD_REPEATS:
        return 0.0

    index = ((phase - phase.min()) * bins_per_cycle).astype(int)
    nbins = int(index.max()) + 1
    finite = np.isfinite(field)
    counts = np.bincount(index[finite].ravel(), minlength=nbins).astype(float)
    totals = np.bincount(index[finite].ravel(),
                         weights=field[finite].ravel(), minlength=nbins)

    filled = counts > 0
    if filled.sum() < 3 * bins_per_cycle:
        return 0.0
    profile = np.zeros(nbins, dtype=float)
    profile[filled] = totals[filled] / counts[filled]
    profile[~filled] = profile[filled].mean()
    profile -= profile.mean()

    # A correlation does not care how small the numbers are, so a profile that
    # is pure averaged noise can still correlate strongly by chance -- which is
    # what happened when a candidate wave ran across the stripes instead of
    # along them and the projection came out flat. Require the profile to be
    # modulated by more than averaging noise would leave behind.
    per_bin = float(counts[filled].mean())
    surface_noise = float(np.nanstd(field[finite]))
    if per_bin > 0 and surface_noise > 0:
        if profile.std() < 3.0 * surface_noise / math.sqrt(per_bin):
            return 0.0

    def correlation_at(lag: int) -> float:
        if lag < 1 or lag >= profile.size:
            return 0.0
        a, b = profile[:-lag], profile[lag:]
        denominator = math.sqrt(float(np.dot(a, a)) * float(np.dot(b, b)))
        return float(np.dot(a, b) / denominator) if denominator > 0 else 0.0

    whole = correlation_at(bins_per_cycle)
    half = correlation_at(bins_per_cycle // 2)
    return whole - half


# --------------------------------------------------------------------------
# texture
# --------------------------------------------------------------------------

def correlation_length(data: np.ndarray, pixel_size: float) -> float:
    """
    The distance over which the surface stops resembling itself.

    Taken as the radius at which the autocorrelation first falls to 1/e. Small
    means fine texture, large means broad features -- it is the single number
    that best separates a grainy film from a surface with big structures, and
    it is what the roughness-bias correction needs.
    """
    field = np.nan_to_num(data - np.nanmean(data))
    if field.size < 64:
        return float("nan")
    spectrum = np.abs(np.fft.fft2(field)) ** 2
    acf = np.real(np.fft.ifft2(spectrum))
    acf = np.fft.fftshift(acf)
    peak = acf.max()
    if peak <= 0:
        return float("nan")
    acf = acf / peak

    h, w = acf.shape
    cy, cx = h // 2, w // 2
    yy, xx = np.mgrid[0:h, 0:w]
    radius = np.hypot(yy - cy, xx - cx).astype(int)
    profile = np.bincount(radius.ravel(), acf.ravel()) / np.bincount(radius.ravel())

    below = np.flatnonzero(profile < 1.0 / math.e)
    if below.size == 0:
        return float("nan")
    return float(below[0] * pixel_size)


def height_shape(data: np.ndarray) -> dict:
    """The shape of the height distribution, which says a lot about the sample."""
    values = data[np.isfinite(data)]
    if values.size < 16:
        return {"skewness": 0.0, "kurtosis": 0.0, "bimodality": 0.0}

    centred = values - values.mean()
    sd = float(centred.std())
    if sd <= 0:
        return {"skewness": 0.0, "kurtosis": 0.0, "bimodality": 0.0}

    skew = float(np.mean(centred ** 3) / sd ** 3)
    kurt = float(np.mean(centred ** 4) / sd ** 4 - 3.0)

    # Sarle's bimodality coefficient: above ~0.55 suggests two populations,
    # which is what a surface with a film and exposed substrate looks like.
    n = values.size
    denominator = kurt + 3.0 * (n - 1) ** 2 / ((n - 2) * (n - 3)) if n > 3 else None
    bimodality = float((skew ** 2 + 1.0) / denominator) if denominator else 0.0

    return {"skewness": skew, "kurtosis": kurt, "bimodality": bimodality}


# --------------------------------------------------------------------------
# the whole set
# --------------------------------------------------------------------------

@dataclass
class Features:
    """Every measurement, for one scan."""

    # form -- what the instrument added
    tilt: float = 0.0
    background_order: int = 0
    explained_by_degree: dict[int, float] = field(default_factory=dict)

    # lines -- scan-row defects
    row_banding: float = 0.0
    row_step_fraction: float = 0.0

    # objects -- what departs from the surface, and which way
    object_fraction: float = 0.0
    raised_fraction: float = 0.0
    sunken_fraction: float = 0.0
    # +1 raised, -1 sunken, 0 neither or both. The single number that separates
    # grains on a substrate from pores in a film, which the count alone cannot.
    object_polarity: int = 0
    object_count: int = 0
    object_median_size: float = 0.0
    object_size_spread: float = 0.0
    object_elongation: float = 0.0

    # periodic structure
    periodicity: float = 0.0
    period_angle: float = float("nan")
    period_length: float = float("nan")
    # How convincingly the repeat showed up in the image itself, 0 to 2. It is
    # kept because it separates an artificial pattern from a natural one: the
    # calibration grating scores 1.9, while the natural surfaces in the pool
    # that repeat at all sit between 0.5 and 0.65.
    period_confirmed: float = 0.0

    # texture
    rms: float = 0.0
    correlation_length: float = float("nan")
    skewness: float = 0.0
    kurtosis: float = 0.0
    bimodality: float = 0.0

    # context
    scan_size: float = 0.0
    pixel_size: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def measure(channel: Channel) -> Features:
    """
    Measure everything, on the surface with its background removed.

    The background is taken out first because almost every descriptor is about
    the surface, not about the tilt the instrument added -- roughness,
    periodicity and object detection are all distorted by a residual slope. The
    tilt itself is kept as its own number.
    """
    from afm_copilot.decide import choose_background_degree

    data = np.asarray(channel.data, dtype=float)
    pixel = channel.pixel_size

    tilt = background_explains(data, 1)
    degree, explained = choose_background_degree(data)
    flat = subtract_background(data, max(1, degree))

    above, below = detect_features(flat)
    raised, sunken = float(above.mean()), float(below.mean())
    # Count and size the side that actually carries the features. Measuring
    # both together would average a grain's diameter with a pore's, and the
    # answer would describe neither.
    # Which side dominates, and only when it clearly does. A close-packed layer
    # of spheres has no background to stand clear of, so what little it reports
    # is the gaps between them -- and calling that "pitted" would describe the
    # sample backwards.
    if sunken > 2 * raised:
        polarity, of_interest = -1, below
    elif raised > 2 * sunken:
        polarity, of_interest = +1, above
    else:
        polarity, of_interest = 0, above | below

    stats = object_statistics(of_interest, pixel)
    period = periodicity(flat, pixel)
    shape = height_shape(flat)

    return Features(
        tilt=tilt,
        background_order=degree,
        explained_by_degree=explained,
        row_banding=row_banding(flat),
        row_step_fraction=row_step_fraction(flat),
        object_fraction=float((above | below).mean()),
        raised_fraction=raised,
        sunken_fraction=sunken,
        object_polarity=polarity,
        periodicity=period["periodicity"],
        period_angle=period["period_angle"],
        period_length=period["period_length"],
        period_confirmed=period.get("period_confirmed", 0.0),
        rms=float(np.nanstd(flat)),
        correlation_length=correlation_length(flat, pixel),
        scan_size=channel.xreal,
        pixel_size=pixel,
        **stats,
        **shape,
    )
