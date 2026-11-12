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
from afm_copilot.morphology import MorphologyReview

RNG = np.random.default_rng(20260902)
N = 256


def surface(data: np.ndarray) -> Channel:
    return Channel(name="Height", data=data, xreal=5e-6, yreal=5e-6)


def coords():
    y, x = np.mgrid[0:N, 0:N].astype(float) / N - 0.5
    return x, y


def flat(noise: float = 1e-9, seed: int = 101) -> np.ndarray:
    # Its own generator, not the shared one. Sharing made every fixture depend
    # on which tests had run before it, so adding a test three files away
    # changed this one's data and its verdict with it.
    return np.random.default_rng(seed).normal(0.0, noise, (N, N))


def textured(roughness: float = 1e-9, seed: int = 202) -> np.ndarray:
    """A surface with structure of its own, not white noise."""
    data = np.random.default_rng(seed).normal(0.0, roughness, (N, N))
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


def test_a_pattern_along_the_slow_axis_is_not_row_aligned():
    """
    Row alignment removes whatever each row's median says, so it is safe only
    when those medians carry nothing. A honeycomb lost a quarter of its
    periodicity to it and came back wavy.
    """
    _, y = coords()
    striped = textured(1e-9) + 40e-9 * np.sin(2 * np.pi * y * 9)
    plan = plan_for(surface(striped))
    assert plan.rows_are_structure
    assert not plan.line_defects
    assert plan.recipe_key == "roughness-ready"


def test_stripes_along_the_fast_axis_are_left_alone_by_this():
    """
    Vertical stripes give identical row medians, so alignment cannot hurt them
    -- and a calibration grating measured before and after is unchanged.
    """
    x, _ = coords()
    striped = textured(1e-9) + 40e-9 * np.sin(2 * np.pi * x * 9)
    assert not plan_for(surface(striped)).rows_are_structure


def test_wandering_row_offsets_are_still_a_defect():
    """
    The guard must not excuse real banding: a drifting offset wanders and
    never comes back, which is what separates it from a pattern.
    """
    data = textured() + RNG.normal(0.0, 3e-9, (N, 1)).cumsum(axis=0) * 0.05
    plan = plan_for(surface(data))
    assert not plan.rows_are_structure


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


def test_distinct_terraces_prefer_facet_levelling():
    """A stepped film is not an object field for the background fitter."""
    from afm_copilot.gwy_io import Channel

    data = np.random.default_rng(17).normal(0.0, 0.3e-9, (256, 256))
    data[:, 256 // 3:2 * 256 // 3] += 20e-9
    data[:, 2 * 256 // 3:] += 40e-9
    plan = plan_for(Channel(name="Height", data=data,
                            xreal=10e-6, yreal=10e-6))

    assert plan.has_terraces
    assert not plan.has_objects
    assert plan.recipe_key == "facet-terraces"


def test_tilted_terraces_are_found_from_the_dominant_local_facet():
    """A height step must not rotate the plane used to reveal that step."""
    x, _ = coords()
    data = textured(0.25e-9, seed=218) + 260e-9 * x
    data[:, N // 3:2 * N // 3] += 35e-9
    data[:, 2 * N // 3:] += 70e-9

    plan = plan_for(surface(data))

    assert plan.has_terraces
    assert not plan.has_objects
    assert plan.recipe_key == "facet-terraces"
    assert any("dominant local facet" in note for note in plan.notes)


def test_dense_particles_are_not_mistaken_for_terraces():
    """Repeated compact peaks are morphology, not broad height plateaux."""
    x, y = coords()
    data = textured(0.3e-9, seed=219) + 180e-9 * x
    for cx in np.linspace(-0.4, 0.4, 7):
        for cy in np.linspace(-0.4, 0.4, 7):
            radius = (x - cx) ** 2 + (y - cy) ** 2
            data += 25e-9 * np.exp(-radius / 0.0015)

    plan = plan_for(surface(data))

    assert not plan.has_terraces
    assert plan.recipe_key != "facet-terraces"


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
    Two real failures, one on each side of this.

    A second-order fit on a background measuring 0% tilt invents curvature at
    the corners. But levelling with the object still in the fit tilts the plane
    towards it and leaves the base sloped, which the user reports as the
    commonest and hardest fault of all -- so the fit is masked either way, and
    only the order follows the background.
    """
    plan = plan_for(surface(with_object(flat())))
    assert plan.has_objects
    assert plan.background_degree == 0
    assert plan.recipe_key != "isolate-objects"


def test_objects_on_a_curved_background_do_get_the_polynomial():
    x, y = coords()
    curved = textured(2e-9) + 300e-9 * (x ** 2 + y ** 2)
    plan = plan_for(surface(with_object(curved)))
    assert plan.has_objects
    assert plan.recipe_key == "isolate-objects"


def test_continuous_morphology_review_vetoes_automatic_object_masking():
    """Vision may stop a false object interpretation, never strengthen one."""
    review = MorphologyReview(
        scan="close-packed",
        family="granular_continuous",
        effect="restrict",
        source="vision-review",
        evidence=("texture occupies the whole field",),
    )
    plan = plan_for(surface(with_object(bowed())), morphology_review=review)

    assert not plan.has_objects
    assert plan.morphology_restricted
    assert plan.background_degree <= 1
    assert plan.recipe_key == "level-only"
    assert any("Automatic masking" in note for note in plan.notes)
    assert not any("so the lines are straightened" in note
                   for note in plan.notes)
    assert not any("higher order finds no more" in note
                   for note in plan.notes)


def test_advisory_morphology_review_does_not_change_the_recipe():
    review = MorphologyReview(
        scan="candidate",
        family="granular_continuous",
        effect="advisory",
        source="vision-review",
    )
    ordinary = plan_for(surface(with_object(bowed())))
    reviewed = plan_for(surface(with_object(bowed())),
                        morphology_review=review)

    assert not reviewed.morphology_restricted
    assert reviewed.recipe_key == ordinary.recipe_key
    assert reviewed.has_objects == ordinary.has_objects


def test_operator_mask_overrides_a_semantic_veto():
    """A hand-drawn correction target is stronger evidence than a label."""
    data = with_object(flat())
    operator_mask = np.zeros_like(data, dtype=bool)
    operator_mask[90:166, 90:166] = True
    review = MorphologyReview(
        scan="reviewed",
        family="granular_continuous",
        effect="restrict",
        source="vision-review",
    )

    plan = plan_for(surface(data), operator_mask=operator_mask,
                    morphology_review=review)

    assert plan.has_objects
    assert not plan.morphology_restricted
    assert plan.operator_mask is not None
    assert plan.recipe_key == "isolate-objects-flat"


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
