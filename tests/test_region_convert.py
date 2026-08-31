"""4B — label images ⇄ regions, without losing holes or components.

The claim this module makes is a ROUND TRIP, so the oracle is the input
itself: convert and convert back, and the array must be identical. That
is a strong oracle and a weak one at the same time — strong because
nothing about the implementation can fake it, weak because a wrong
STRUCTURE can still rasterize to the right pixels through a union. So the
structural properties the roadmap actually asks for (holes kept,
disconnected components kept, a label's identity kept) are asserted
separately, on the regions themselves, rather than inferred from the
round trip passing.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.region_convert import (
    LabelOverlapError,
    labels_to_regions,
    regions_to_labels,
)
from fermiviewer.calc.region_mask import rasterize

pytestmark = pytest.mark.parser


def _values(labels: np.ndarray) -> dict[str, int]:
    return {f"label_{v}": int(v) for v in np.unique(labels) if v}


def _round_trip(labels: np.ndarray) -> np.ndarray:
    regions = labels_to_regions(labels)
    return regions_to_labels(regions, labels.shape, values=_values(labels))


# ── the round trip ───────────────────────────────────────────────────


def _solid() -> np.ndarray:
    labels = np.zeros((16, 16), dtype=int)
    labels[3:9, 3:9] = 1
    labels[10:14, 10:14] = 2
    return labels


def _holed() -> np.ndarray:
    labels = np.zeros((16, 16), dtype=int)
    labels[2:14, 2:14] = 1
    labels[6:10, 6:10] = 0
    return labels


def _island_in_hole() -> np.ndarray:
    labels = _holed()
    labels[7:9, 7:9] = 1
    return labels


def _disconnected() -> np.ndarray:
    labels = np.zeros((14, 14), dtype=int)
    labels[2:6, 2:6] = 1
    labels[8:12, 8:12] = 1
    return labels


def _diagonal_pair() -> np.ndarray:
    labels = np.zeros((10, 10), dtype=int)
    labels[2, 2] = 1
    labels[3, 3] = 1
    return labels


def _touching_border() -> np.ndarray:
    labels = np.zeros((10, 10), dtype=int)
    labels[0:4, 0:4] = 1
    return labels


CASES = {
    "two solid labels": _solid(),
    "a label with a hole": _holed(),
    "an island inside a hole": _island_in_hole(),
    "one label, two components": _disconnected(),
    "a diagonal pair": _diagonal_pair(),
    "touching the array border": _touching_border(),
    "the whole image": np.ones((8, 8), dtype=int),
    "one pixel, sparse value": np.pad(np.array([[7]]), 5),
    "a one-pixel line": np.pad(np.ones((1, 8), dtype=int), 3),
    "nothing at all": np.zeros((6, 6), dtype=int),
}


@pytest.mark.parametrize(("name", "labels"), list(CASES.items()))
def test_a_label_image_survives_the_round_trip_exactly(name: str, labels: np.ndarray) -> None:
    assert np.array_equal(_round_trip(labels), labels), name


@pytest.mark.parametrize("seed", range(40))
def test_random_label_images_survive_the_round_trip(seed: int) -> None:
    """Randomized because the structural cases are the ones I thought of.

    A 4-value map at this size reliably produces touching labels,
    diagonal contacts, holes and stray single pixels without anyone
    choosing them.
    """
    labels = np.random.default_rng(seed).integers(0, 4, (13, 13))
    assert np.array_equal(_round_trip(labels), labels)


def test_the_border_pad_is_what_makes_border_contact_exact() -> None:
    """`find_contours` leaves a path OPEN where a feature meets the edge
    of the array, and closing it afterwards cuts the corner — a 4x4 block
    in a corner came back as 6 pixels of 16. Asserted as a NUMBER so the
    test says what the failure looked like."""
    labels = _touching_border()
    assert (_round_trip(labels) != 0).sum() == 16


# ── structure, not just pixels ───────────────────────────────────────


def test_a_hole_is_a_hole_and_not_a_second_outline() -> None:
    """The roadmap asks for holes to survive, which the round trip alone
    does not show: a hole recorded as a separate `exclude` part, or as a
    part on the wrong outline, can rasterize to the same pixels."""
    (region,) = labels_to_regions(_holed())
    (part,) = region.parts
    assert part.mode == "include"
    assert len(part.shape.holes) == 1
    hole = part.shape.holes[0]
    outline = part.shape.outline
    assert outline is not None
    assert hole[:, 0].min() > outline[:, 0].min(), "the hole is inside"
    assert hole[:, 0].max() < outline[:, 0].max()


def test_an_island_inside_a_hole_is_its_own_part() -> None:
    """Three nested rings: material, hole, material. The middle one is a
    hole of the OUTER part, and the innermost is a part of its own — not
    a hole of a hole, and not attached to the wrong outline."""
    (region,) = labels_to_regions(_island_in_hole())
    assert len(region.parts) == 2
    outer, island = sorted(region.parts, key=lambda p: -np.ptp(p.shape.outline[:, 0]))
    assert len(outer.shape.holes) == 1
    assert len(island.shape.holes) == 0
    hole = outer.shape.holes[0]
    assert np.ptp(island.shape.outline[:, 0]) < np.ptp(hole[:, 0]), (
        "the island sits inside the hole it was cut from"
    )


def test_a_disconnected_label_stays_one_region_with_two_parts() -> None:
    """A label is one thing even when its pixels are not touching. Two
    regions would lose that identity, which is the other half of what the
    roadmap means by not losing disconnected components."""
    regions = labels_to_regions(_disconnected())
    assert len(regions) == 1
    assert len(regions[0].parts) == 2
    assert all(p.mode == "include" for p in regions[0].parts)


def test_a_diagonal_pair_is_two_parts_of_one_region_not_a_hole() -> None:
    """The trap that decided the design. Grouping by 8-connected
    components makes this ONE component, but marching squares traces it
    as TWO rings — so "largest ring is the outline, the rest are holes"
    turns the second pixel into a hole. That rasterizes, looks like a
    shape, and is not the label."""
    regions = labels_to_regions(_diagonal_pair())
    assert len(regions) == 1
    assert len(regions[0].parts) == 2
    assert all(len(p.shape.holes) == 0 for p in regions[0].parts)
    assert rasterize(regions[0], (10, 10)).sum() == 2


def test_outlines_are_in_full_image_coordinates() -> None:
    """Tracing runs on a crop of the label's bounding box, so every ring
    is shifted back by the crop origin on the way out. A label AT the
    origin has a zero offset and would look correct with the shift
    dropped, so this one is deliberately far from it."""
    labels = np.zeros((60, 60), dtype=int)
    labels[40:50, 44:54] = 7
    (region,) = labels_to_regions(labels)
    outline = region.parts[0].shape.outline
    assert outline is not None
    assert outline[:, 0].min() == pytest.approx(39.5)
    assert outline[:, 1].min() == pytest.approx(43.5)
    assert np.array_equal(rasterize(region, (60, 60)), labels == 7)


def test_the_single_ring_fast_path_agrees_with_the_general_one() -> None:
    """A label with one ring skips the nesting computation entirely.

    That is a second implementation of the same answer, which is how a
    rule starts meaning two things — so the two are compared directly
    rather than trusted to agree. The general path is reached by giving
    the same label a hole, then filling it back in.
    """
    labels = np.zeros((20, 20), dtype=int)
    labels[4:16, 4:16] = 1
    (fast,) = labels_to_regions(labels)

    # force the general path by tracing a mask that also has a hole ring,
    # then check the outline it produces for the SAME solid boundary
    holed = labels.copy()
    holed[8:12, 8:12] = 0
    (general,) = labels_to_regions(holed)
    assert np.array_equal(fast.parts[0].shape.outline, general.parts[0].shape.outline), (
        "the two paths must trace the same outer boundary"
    )
    assert len(fast.parts[0].shape.holes) == 0
    assert len(general.parts[0].shape.holes) == 1


def test_conversion_is_deterministic() -> None:
    labels = _island_in_hole()
    first = labels_to_regions(labels)
    second = labels_to_regions(labels)
    assert [r.id for r in first] == [r.id for r in second]
    for a, b in zip(first, second, strict=True):
        assert len(a.parts) == len(b.parts)
        for pa, pb in zip(a.parts, b.parts, strict=True):
            assert np.array_equal(pa.shape.outline, pb.shape.outline)


def test_ids_name_the_label_and_come_back_in_value_order() -> None:
    labels = np.zeros((10, 10), dtype=int)
    labels[1:3, 1:3] = 5
    labels[6:8, 6:8] = 2
    regions = labels_to_regions(labels)
    assert [r.id for r in regions] == ["label_2", "label_5"]
    assert [r.id for r in labels_to_regions(labels, prefix="grain")] == [
        "grain_2",
        "grain_5",
    ]


# ── refusals ─────────────────────────────────────────────────────────


def test_overlapping_regions_cannot_become_a_label_image() -> None:
    """A label image holds one value per pixel, so two regions covering
    one pixel means a claim is dropped — and whichever rule picked the
    winner would be invisible in the array that came back."""
    labels = np.zeros((12, 12), dtype=int)
    labels[2:8, 2:8] = 1
    (region,) = labels_to_regions(labels)
    shifted = labels.copy() * 0
    shifted[4:10, 4:10] = 2
    (other,) = labels_to_regions(shifted)
    with pytest.raises(LabelOverlapError, match="overlaps"):
        regions_to_labels((region, other), (12, 12))


def test_a_float_label_image_is_refused_rather_than_rounded() -> None:
    """1.9999 is label 1 or label 2 depending on a convention the caller
    knows and this module does not."""
    with pytest.raises(ValueError, match="integer array"):
        labels_to_regions(np.zeros((4, 4), dtype=float))


def test_bad_label_images_are_refused() -> None:
    with pytest.raises(ValueError, match="2-D"):
        labels_to_regions(np.zeros((2, 2, 2), dtype=int))
    with pytest.raises(ValueError, match="non-negative"):
        labels_to_regions(-np.ones((4, 4), dtype=int))


def test_a_region_cannot_be_written_as_background() -> None:
    (region,) = labels_to_regions(_touching_border())
    with pytest.raises(ValueError, match="background"):
        regions_to_labels((region,), (10, 10), values={region.id: 0})


def test_a_region_with_no_value_is_refused() -> None:
    (region,) = labels_to_regions(_touching_border())
    with pytest.raises(ValueError, match="no label value"):
        regions_to_labels((region,), (10, 10), values={"someone else": 1})


def test_regions_take_1_to_n_when_no_values_are_given() -> None:
    regions = labels_to_regions(_solid())
    out = regions_to_labels(regions, (16, 16))
    assert sorted(np.unique(out).tolist()) == [0, 1, 2]
