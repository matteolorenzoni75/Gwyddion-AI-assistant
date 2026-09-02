"""
Known-answer tests for the automatic decisions.

Each surface here has a right answer built into it. The one that matters most
is the flat background: fitting curvature into a surface that has none is the
mistake that already happened on real data, and it looked like a 35%
improvement in the numbers.
"""

from __future__ import annotations

import numpy as np
import pytest

from afm_copilot.decide import (choose_background_degree, detect_objects,
                                plan_for, residual_after_background)
from afm_copilot.gwy_io import Channel

RNG = np.random.default_rng(20260902)
N = 256


def surface(data: np.ndarray) -> Channel:
    return Channel(name="Height", data=data, xreal=5e-6, yreal=5e-6)


def coords():
    y, x = np.mgrid[0:N, 0:N].astype(float) / N - 0.5
    return x, y


def flat(noise: float = 1e-9) -> np.ndarray:
    return RNG.normal(0.0, noise, (N, N))


def tilted(slope: float = 100e-9) -> np.ndarray:
    x, _ = coords()
    return slope * x + flat(1e-9)


def bowed(depth: float = 100e-9) -> np.ndarray:
    x, y = coords()
    return depth * (x * x + y * y) + flat(1e-9)


def with_object(base: np.ndarray, height: float = 200e-9,
                size: int = 70) -> np.ndarray:
    out = base.copy()
    start = (N - size) // 2
    out[start:start + size, start:start + size] += height
    return out


# --------------------------------------------------------------- degree

def test_flat_background_needs_no_correction():
    """The mistake that already happened on real data, as a test."""
    degree, _ = choose_background_degree(flat())
    assert degree == 0


def test_tilt_needs_first_order_and_no_more():
    degree, _ = choose_background_degree(tilted())
    assert degree == 1


def test_bow_needs_second_order():
    degree, _ = choose_background_degree(bowed())
    assert degree == 2


def test_higher_orders_are_not_taken_for_free():
    """A pure bow must not pull in a third order it does not need."""
    degree, residuals = choose_background_degree(bowed(), max_degree=4)
    assert degree == 2
    # Order 3 was tried; it simply did not help enough to be used.
    assert 3 in residuals


def test_residual_falls_when_the_order_matches_the_surface():
    data = bowed()
    assert residual_after_background(data, 2) < residual_after_background(data, 1)
    assert residual_after_background(data, 1) < residual_after_background(data, 0)


# --------------------------------------------------------------- objects

def test_an_object_is_found():
    mask = detect_objects(with_object(flat()))
    fraction = mask.mean()
    # A 70x70 square in a 256x256 frame is about 7.5% of it.
    assert 0.04 < fraction < 0.12


def test_a_bare_surface_has_no_objects():
    assert detect_objects(flat()).mean() < 0.01


def test_the_object_is_kept_out_of_the_background_fit():
    """
    The point of masking, as a number.

    A tall object on a bowed background pulls a fit made through it. Fitting
    around the mask has to leave a smaller residual on the background itself.
    """
    data = with_object(bowed())
    mask = detect_objects(data)

    through = residual_after_background(data, 2, mask=None)
    around = residual_after_background(data, 2, mask=mask)
    assert around < through / 2


# ------------------------------------------------------------------ plan

def test_a_flat_scan_is_left_alone():
    plan = plan_for(surface(flat()))
    assert plan.background_degree == 0
    assert plan.already_levelled
    assert plan.recipe_key == "level-only"
    assert any("already levelled" in n for n in plan.notes)


def test_a_bowed_scan_with_objects_gets_the_masked_recipe():
    plan = plan_for(surface(with_object(bowed())))
    assert plan.has_objects
    assert plan.background_degree == 2
    assert plan.recipe_key == "isolate-objects"


def test_objects_on_a_flat_background_do_not_get_a_polynomial():
    """
    The real scan that failed.

    Its background measured 0% tilt, and a second-order fit invented curvature
    at the corners. With objects present but a flat background, the answer is
    the plain tidy-up, not the masked polynomial.
    """
    plan = plan_for(surface(with_object(flat())))
    assert plan.has_objects
    assert plan.background_degree == 0
    assert plan.recipe_key != "isolate-objects"


def test_objects_are_measured_against_the_majority_surface():
    """
    A known limit, recorded so it is not mistaken for a bug.

    Objects are found relative to the median height, so the detector can only
    ever report a minority of the frame. When a raised region covers most of
    it, that region becomes the reference and the *lower* part is what stands
    out. The answer is not wrong -- with no majority background there is
    nothing to fit a background on -- but it means a large object is reported
    as a small one, not as a large one.
    """
    data = flat()
    data[:, : int(N * 0.7)] += 300e-9      # 70% of the frame raised
    plan = plan_for(surface(data))

    # Never the majority, whatever the surface looks like.
    assert plan.object_fraction < 0.5


def test_the_plan_shows_its_working():
    plan = plan_for(surface(bowed()))
    text = plan.explain()
    assert "order 0" in text and "order 2" in text
    # It reports how much each order accounts for, and where it settles --
    # which is the evidence for the choice, not just the choice.
    assert "%" in text
    assert "settles here" in text


def test_a_bowl_rim_is_not_mistaken_for_objects():
    """
    A bowed surface has a raised rim. Marking it as objects would make the
    background be fitted around the very shape it exists to remove.
    """
    plan = plan_for(surface(bowed()))
    assert not plan.has_objects
    assert plan.background_degree == 2


def test_a_tilted_surface_has_no_objects_either():
    """The high side of a tilt is not an object."""
    plan = plan_for(surface(tilted()))
    assert not plan.has_objects
    assert plan.background_degree == 1
