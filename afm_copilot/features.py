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

def detect_objects(data: np.ndarray, threshold: float = 0.30) -> np.ndarray:
    """
    Pixels standing clear of the background.

    Measured against the median, so a large object does not drag the reference
    up and hide itself. Known limit: once objects cover more than about half
    the frame the median sits inside them, and the minority is what stands out.
    """
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros(data.shape, dtype=bool)
    base = float(np.median(finite))
    span = float(finite.max() - finite.min())
    if span <= 0:
        return np.zeros(data.shape, dtype=bool)
    return np.nan_to_num(data, nan=base) > base + threshold * span


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

def periodicity(data: np.ndarray, pixel_size: float) -> dict:
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
    if not usable.any():
        return {"periodicity": 0.0, "period_angle": float("nan"),
                "period_length": float("nan")}

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

    significant = usable & (ring_median > 0)
    if not significant.any():
        return {"periodicity": 0.0, "period_angle": float("nan"),
                "period_length": float("nan")}

    contrast = np.zeros_like(spectrum)
    contrast[significant] = spectrum[significant] / ring_median[significant]

    strength = float(contrast.max())
    py, px = np.unravel_index(int(np.argmax(contrast)), contrast.shape)
    dy, dx = py - cy, px - cx

    # The stripes run perpendicular to the direction of the peak.
    angle = math.degrees(math.atan2(dy, dx)) % 180.0
    freq = math.hypot(dy / h, dx / w)
    length = (pixel_size / freq) if freq > 0 else float("nan")

    return {"periodicity": strength,
            "period_angle": (angle + 90.0) % 180.0,
            "period_length": length}


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

    # objects -- what sits on the surface
    object_fraction: float = 0.0
    object_count: int = 0
    object_median_size: float = 0.0
    object_size_spread: float = 0.0
    object_elongation: float = 0.0

    # periodic structure
    periodicity: float = 0.0
    period_angle: float = float("nan")
    period_length: float = float("nan")

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

    objects = detect_objects(flat)
    stats = object_statistics(objects, pixel)
    period = periodicity(flat, pixel)
    shape = height_shape(flat)

    return Features(
        tilt=tilt,
        background_order=degree,
        explained_by_degree=explained,
        row_banding=row_banding(flat),
        row_step_fraction=row_step_fraction(flat),
        object_fraction=float(objects.mean()),
        periodicity=period["periodicity"],
        period_angle=period["period_angle"],
        period_length=period["period_length"],
        rms=float(np.nanstd(flat)),
        correlation_length=correlation_length(flat, pixel),
        scan_size=channel.xreal,
        pixel_size=pixel,
        **stats,
        **shape,
    )
