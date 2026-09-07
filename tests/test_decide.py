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


def textured(roughness: float = 1e-9) -> np.ndarray:
    """A surface with structure of its own, not white noise."""
    data = RNG.normal(0.0, roughness, (N, N))
    for _ in range(8):
        data = (data + np.roll(data, 1, 0) + np.roll(data, 1, 1)) / 3.0
    return data * (roughness / max(data.std(), 1e-18))


def test_a_nearly_perfect_background_is_still_finished_properly():
    """
    The failure the relative test exists for.

    On a polished substrate order 1 explained 99.59% and order 2 explained
    99.95%, so measured against the whole the extra 0.36% looked negligible and
    order 1 was chosen -- leaving an 18 nm bow on a surface whose noise is
    0.7 nm. Against what remained, that 0.36% was 88% of it.
    """
    # The proportions matter, and are taken from the real scan: a large tilt
    # with a small bow riding on it, so that the plane alone already accounts
    # for almost everything and the leftover curvature looks negligible next
    # to the whole while being nearly all of what is left.
    x, y = coords()
    data = textured(0.2e-9) + 900e-9 * x + 60e-9 * (x ** 2 + y ** 2)
    degree, explained = choose_background_degree(data)
    assert explained[1] > 0.98, "the plane alone should already explain most"
    assert explained[2] - explained[1] < 0.02, "and the bow is a sliver of it"
    assert degree == 2


def test_a_surface_of_its_own_shape_is_left_alone():
    """
    The case the old rule protected, and which must keep working.

    A scan the instrument had already levelled climbed 0%, 46%, 65% order after
    order. Every one of those orders was finding the sample.
    """
    assert choose_background_degree(textured())[0] == 0


def test_curvature_has_to_earn_more_than_tilt_does():
    """
    Three large domes: a second-order fit explains a fair share of the frame
    and would be carving the domes out of it.
    """
    x, y = coords()
    domes = textured(2e-9)
    for cx, cy in ((-0.25, -0.2), (0.2, 0.15), (0.3, -0.3)):
        r2 = (x - cx) ** 2 + (y - cy) ** 2
        domes += 300e-9 * np.exp(-r2 / 0.02)
    degree, explained = choose_background_degree(domes)
    assert explained[2] < 0.60, "the fixture must not be background-dominated"
    assert degree < 2


def test_a_flat_scan_with_damaged_lines_is_not_left_alone():
    """
    'Level only' says so itself: do not use it when the image has banding or
    scars, it will not touch them. Nothing was checking, and 23 of the 30 scans
    routed there in one batch had rows out of line -- the worst at 45% -- every
    one of them left as it was.
    """
    data = textured()
    offsets = RNG.normal(0.0, 3e-9, (N, 1))
    plan = plan_for(surface(data + offsets))
    assert plan.already_levelled or plan.background_degree == 0
    assert plan.line_defects
    assert plan.recipe_key != "level-only"


def test_a_clean_flat_scan_is_still_left_alone():
    """And the conservative choice must survive where it is right."""
    plan = plan_for(surface(textured()))
    assert not plan.line_defects
    assert plan.recipe_key == "level-only"


def test_a_background_that_dominates_is_taken_even_if_it_never_settles():
    """
    Flakes on mica: order 1 explained 34%, order 2 explained 88%, and nothing
    settled by order 3 -- so the old rule fell back to the lowest order and
    left the bow in.
    """
    x, y = coords()
    data = textured(3e-9) + 600e-9 * (x ** 2 + y ** 2) + 200e-9 * x
    degree, explained = choose_background_degree(data)
    assert explained[2] >= 0.80
    assert degree == 2


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
