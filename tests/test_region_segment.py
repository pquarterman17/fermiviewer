"""4C-3 — segmentation, particles and grains over canonical regions.

Expectations come from OUTSIDE the code under test wherever a claim could
otherwise be confirmed by the implementation making it:

* the placement oracle is a nested loop over the written definition of an
  inclusive rectangle plus the mask, never `place_labels` itself;
* rectangular parity is asserted against `calc.roi.embed_rect_roi`, the
  pre-4C path, so "preserve existing behavior" is a comparison rather
  than an assertion about the new code;
* the threshold-isolation test is written in both directions — the
  answer must not move when an out-of-mask blob appears, AND must move
  when the same blob is inside the mask, or the test would pass on an
  implementation that ignored the values entirely.
"""

from __future__ import annotations

import tracemalloc
from typing import Any

import numpy as np
import pytest

import fermiviewer.ops as ops
from fermiviewer.calc.region_mask import rasterize
from fermiviewer.calc.region_segment import place_labels, place_values, region_values
from fermiviewer.calc.regions import Part, Region, Shape
from fermiviewer.calc.roi import embed_rect_roi, extract_rect_roi
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops import catalogue_structure

pytestmark = pytest.mark.parser


def _image(data: np.ndarray) -> DataStruct:
    return DataStruct(
        data=np.asarray(data, dtype=np.float64),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
        metadata={"source": "synthetic"},
    )


def _named(result: Any, name: str) -> dict[str, Any]:
    return next(o for o in result.value["outputs"] if o["name"] == name)["data"]


def _has(result: Any, name: str) -> bool:
    return any(o["name"] == name for o in result.value["outputs"])


def _labels(result: Any) -> np.ndarray:
    return np.asarray(_named(result, "labels")["values"])


def _rect(r0: int, c0: int, r1: int, c1: int) -> list[dict[str, Any]]:
    """One `rect` part in canonical 0-based INCLUSIVE (row, col)."""
    return [{"kind": "rect", "bounds": [[r0, c0, r1, c1]]}]


# ── the placement oracle ─────────────────────────────────────────────


def _placed_by_hand(
    block: np.ndarray,
    shape: tuple[int, int],
    rect: tuple[int, int, int, int],
    mask: np.ndarray | None,
) -> np.ndarray:
    """Expected full-image labels, built from the written rules.

    Loops over the definition — 1-based inclusive rect, clear outside the
    mask, renumber survivors ascending — rather than calling the code
    under test with different arguments.
    """
    r1, c1, r2, c2 = rect
    out = np.zeros(shape, dtype=int)
    for r in range(r1 - 1, r2):
        for c in range(c1 - 1, c2):
            v = int(block[r - (r1 - 1), c - (c1 - 1)])
            if mask is not None and not mask[r, c]:
                continue
            out[r, c] = v
    dropped = mask is not None and any(
        int(block[r - (r1 - 1), c - (c1 - 1)]) != 0
        for r in range(r1 - 1, r2)
        for c in range(c1 - 1, c2)
        if not mask[r, c]
    )
    if not dropped:
        return out
    survivors = sorted({int(v) for v in out.ravel() if v != 0})
    renumber = {old: i + 1 for i, old in enumerate(survivors)}
    return np.asarray([[renumber.get(int(v), 0) for v in row] for row in out], dtype=int)


# ── place_labels ─────────────────────────────────────────────────────


def test_a_rectangular_region_reproduces_the_legacy_embed_exactly() -> None:
    """The pre-4C path is `embed_rect_roi`. A rect region must not move a
    single pixel of it — gaps in the incoming numbering included, which is
    why the block below deliberately skips label 2."""
    block = np.array([[1, 1, 0], [0, 3, 3], [4, 0, 0]], dtype=int)
    rect = (2, 3, 4, 5)
    got, clipped = place_labels(block, (6, 7), rect)
    assert np.array_equal(got, embed_rect_roi(block, (6, 7), rect))
    assert np.array_equal(got, _placed_by_hand(block, (6, 7), rect, None))
    assert clipped is False
    assert sorted(set(got.ravel().tolist())) == [0, 1, 3, 4], "gaps must survive"


def test_labels_never_appear_outside_an_irregular_mask() -> None:
    block = np.array([[1, 1, 1], [1, 1, 1], [1, 1, 1]], dtype=int)
    shape = (5, 5)
    rect = (1, 1, 3, 3)
    mask = np.zeros(shape, dtype=bool)
    mask[0:3, 0:3] = True
    mask[1, 1] = False  # a one-pixel hole
    got, clipped = place_labels(block, shape, rect, mask)
    assert clipped is True
    assert got[1, 1] == 0, "the hole must be a hole"
    assert np.array_equal(got, _placed_by_hand(block, shape, rect, mask))
    assert not got[3:, :].any() and not got[:, 3:].any()


def test_clipping_renumbers_survivors_gap_free() -> None:
    """Label 2 is entirely outside the mask, so what was 3 must become 2:
    a table indexed by label would otherwise carry an empty row."""
    block = np.array([[1, 2], [3, 3]], dtype=int)
    shape = (2, 2)
    mask = np.array([[True, False], [True, True]])
    got, clipped = place_labels(block, shape, (1, 1, 2, 2), mask)
    assert clipped is True
    assert sorted(set(got.ravel().tolist())) == [0, 1, 2]
    assert got[1, 1] == 2, "the survivor above 2 slides down into its place"
    assert np.array_equal(got, _placed_by_hand(block, shape, (1, 1, 2, 2), mask))


def test_a_mask_that_clears_only_background_changes_nothing() -> None:
    """`clipped` asks whether a LABELLED pixel was dropped. Renumbering on
    a mask that only trims background would silently close `min_area`
    gaps that a rectangular run is required to keep."""
    block = np.array([[1, 0], [0, 3]], dtype=int)
    mask = np.array([[True, False], [True, True]])  # clears only a 0
    got, clipped = place_labels(block, (2, 2), (1, 1, 2, 2), mask)
    assert clipped is False
    assert sorted(set(got.ravel().tolist())) == [0, 1, 3], "the gap must survive"


def test_renumbering_keeps_the_ascending_order_of_the_survivors() -> None:
    """Renumbering is order-preserving: the lowest surviving label becomes
    1, the next becomes 2. A table whose rows are written in label order
    would otherwise be permuted against its own map."""
    block = np.array([[2, 2], [5, 5]], dtype=int)
    mask = np.array([[True, True], [True, False]])
    got, _ = place_labels(block, (2, 2), (1, 1, 2, 2), mask)
    assert got[0, 0] == 1 and got[1, 0] == 2
    assert 0 in got.ravel().tolist()


def test_place_labels_rejects_a_mismatched_block_and_negative_labels() -> None:
    with pytest.raises(ValueError, match="does not match the rect"):
        place_labels(np.ones((2, 2), dtype=int), (5, 5), (1, 1, 3, 3))
    with pytest.raises(ValueError, match="non-negative"):
        place_labels(-np.ones((3, 3), dtype=int), (5, 5), (1, 1, 3, 3))


# ── place_values ─────────────────────────────────────────────────────


def test_place_values_preserves_class_ids_rather_than_renumbering() -> None:
    """The distinction from `place_labels`. A class map's 3 MEANS class 3;
    sliding it down to 2 because class 2 fell outside the region would
    relabel the specimen."""
    block = np.array([[2, 3], [3, 3]], dtype=int)
    mask = np.array([[False, True], [True, True]])
    got = place_values(block, (2, 2), (1, 1, 2, 2), mask)
    assert got[0, 0] == 0, "outside the region carries the fill"
    assert sorted(set(got.ravel().tolist())) == [0, 3], "3 stays 3"


def test_place_values_fills_outside_the_rect_too() -> None:
    block = np.full((2, 2), 0.75)
    got = place_values(block, (4, 4), (2, 2, 3, 3), None, fill=0.0)
    assert got[0, 0] == 0.0 and got[1, 1] == 0.75
    assert got.dtype == block.dtype


# ── region_values ────────────────────────────────────────────────────


def test_region_values_returns_exactly_the_selected_pixels() -> None:
    values = np.arange(25, dtype=np.float64).reshape(5, 5)
    mask = np.zeros((5, 5), dtype=bool)
    mask[1, 1] = mask[3, 4] = mask[2, 2] = True
    got = region_values(values, (1, 1, 5, 5), mask)
    assert sorted(got.tolist()) == sorted([values[1, 1], values[2, 2], values[3, 4]])
    assert region_values(values, (2, 2, 3, 3)).tolist() == (
        extract_rect_roi(values, (2, 2, 3, 3)).ravel().tolist()
    )


# ── particles ────────────────────────────────────────────────────────


def _two_blobs() -> np.ndarray:
    img = np.zeros((40, 40))
    img[5:12, 5:12] = 10.0
    img[25:32, 25:32] = 10.0
    return img


def test_particles_region_selects_only_the_blob_it_covers() -> None:
    ds = _image(_two_blobs())
    assert _named(ops.run("particles", ds, {}), "n_particles")["value"] == 2
    scoped = ops.run("particles", ds, {"region": _rect(0, 0, 20, 20)})
    assert _named(scoped, "n_particles")["value"] == 1
    labels = _labels(scoped)
    assert labels.shape == (40, 40), "the map stays full-image"
    assert not labels[21:, :].any(), "nothing outside the region is labelled"


def test_the_particle_table_and_the_label_map_share_one_frame() -> None:
    """The table's centroid must locate the blob the map shows.

    `particle_analysis` measures the CROP, so its centroids are crop-local
    while the map is full-image. Before this wave `particles` had no ROI
    and the two frames coincided, which is precisely why cropping it split
    them silently: a 7x7 blob at full-image rows 27-33 inside region
    [20,20,39,39] reported centroid (10, 10) in the table and (30, 30) in
    the map.

    The map is the oracle, and the region is deliberately NOT at the
    origin — an origin-anchored region has a zero offset and would pass
    against the broken code.
    """
    img = np.zeros((40, 40))
    img[26:33, 26:33] = 10.0
    ds = _image(img)

    # Every region is ASYMMETRIC: a square one gives equal row and column
    # offsets, so transposing them would still pass.
    for region in (
        None,
        _rect(20, 12, 39, 35),
        [{"kind": "ellipse", "bounds": [[18, 10, 39, 37]]}],
    ):
        run = ops.run("particles", ds, {} if region is None else {"region": region})
        table = _named(run, "particles")
        row = dict(zip(table["columns"], table["rows"][0], strict=True))
        placed = _labels(run) == int(row["id"])
        got_rows, got_cols = np.nonzero(placed)
        assert row["centroid_row"] == pytest.approx(float(got_rows.mean()) + 1), region
        assert row["centroid_col"] == pytest.approx(float(got_cols.mean()) + 1), region
        assert row["area"] == pytest.approx(float(placed.sum())), region


def test_particles_auto_threshold_ignores_pixels_outside_the_mask() -> None:
    """The scientific claim of this wave, in both directions.

    A bright feature the user drew AROUND must not set the level for the
    pixels they kept — and the same feature inside the region must. A
    one-directional test would pass on an implementation that ignored the
    values altogether.
    """
    base = _two_blobs()
    region = [{"kind": "ellipse", "bounds": [[0, 0, 25, 25]]}]

    def threshold(img: np.ndarray) -> float:
        run = ops.run("particles", _image(img), {"region": region})
        return float(_named(run, "threshold")["value"])

    outside = base.copy()
    outside[0:3, 0:3] = 1000.0  # inside the bounding box, outside the ellipse
    inside = base.copy()
    inside[12:15, 12:15] = 1000.0  # inside the ellipse

    assert threshold(outside) == threshold(base), "an excluded blob must not count"
    assert threshold(inside) != threshold(base), "an included one must"


def test_particles_respects_holes_and_grouped_unions() -> None:
    ds = _image(_two_blobs())
    holed = ops.run(
        "particles",
        ds,
        {
            "region": [
                {"kind": "rect", "bounds": [[0, 0, 20, 20]]},
                {"kind": "rect", "bounds": [[6, 6, 10, 10]], "mode": "exclude"},
            ]
        },
    )
    labels = _labels(holed)
    assert not labels[6:11, 6:11].any(), "an excluded part is a real hole"

    both = ops.run(
        "particles",
        ds,
        {
            "region": [
                {"kind": "rect", "bounds": [[0, 0, 20, 20]], "group": 0},
                {"kind": "rect", "bounds": [[22, 22, 39, 39]], "group": 1},
            ]
        },
    )
    assert _named(both, "n_particles")["value"] == 2, "disconnected groups union"


def test_particles_reports_its_region_and_stays_silent_without_one() -> None:
    ds = _image(_two_blobs())
    assert not _has(ops.run("particles", ds, {}), "region")
    rect = _named(ops.run("particles", ds, {"region": _rect(0, 0, 20, 20)}), "region")
    assert rect["rows"] == [[1, 1, 21, 21]], "1-based inclusive, clamped"
    assert rect["exact_mask"] is False, "a rectangle IS its bounding box"
    ellipse = _named(
        ops.run("particles", ds, {"region": [{"kind": "ellipse", "bounds": [[0, 0, 20, 20]]}]}),
        "region",
    )
    assert ellipse["exact_mask"] is True
    assert ellipse["label_context"] == "exact-mask", "the fill clips before thresholding"


def test_particles_refuses_a_region_that_selects_nothing() -> None:
    with pytest.raises(ValueError, match="selects no pixels"):
        ops.run("particles", _image(_two_blobs()), {"region": _rect(60, 60, 70, 70)})


# ── grains ───────────────────────────────────────────────────────────


def _textured() -> np.ndarray:
    rng = np.random.default_rng(3)
    img = rng.normal(50.0, 5.0, (48, 48))
    img[:24, :] += 30.0
    return img


def test_grains_rect_region_reproduces_the_legacy_roi_string() -> None:
    """`grains` already had a rectangle. The new path must return the same
    labels for the same rectangle, or the migration moved an answer."""
    ds = _image(_textured())
    legacy = ops.run("grains", ds, {"roi": "1,1,24,24", "method": "gradient"})
    migrated = ops.run("grains", ds, {"region": _rect(0, 0, 23, 23), "method": "gradient"})
    assert np.array_equal(_labels(legacy), _labels(migrated))
    assert _named(legacy, "n_grains")["value"] == _named(migrated, "n_grains")["value"]


def test_grains_clips_labels_to_an_irregular_region() -> None:
    ds = _image(_textured())
    run = ops.run(
        "grains",
        ds,
        {"region": [{"kind": "ellipse", "bounds": [[4, 4, 40, 40]]}], "method": "gradient"},
    )
    labels = _labels(run)
    # The corner of the BOUNDING BOX, not of the image: a pixel outside the
    # rect is zero however the mask is handled, so asserting there would
    # pass on an implementation that dropped the mask entirely.
    # The contract, asserted over EVERY pixel rather than a corner that
    # the segmenter might have left as background anyway: the mask is
    # rebuilt here from `calc.region_mask.rasterize`, which is the
    # resolver's own rasterizer and not the placement code under test.
    expected = rasterize(
        Region(id="e", parts=(Part(Shape(kind="ellipse", bounds=(4, 4, 40, 40))),)),
        (48, 48),
    )
    assert not ((labels != 0) & ~expected).any(), "no label may sit outside the region"
    assert labels.max() >= 1
    surviving = sorted({int(v) for v in labels.ravel() if v != 0})
    assert surviving == list(range(1, len(surviving) + 1)), "renumbered gap-free"
    assert _named(run, "region")["label_context"] == "bounding-box", (
        "texture features read a neighbourhood, and saying so is the point"
    )


def test_a_legacy_roi_string_is_reported_clamped_to_the_image() -> None:
    """The rect in provenance is the one the crop USED. An out-of-bounds
    corner is clamped by `calc.roi.roi_slices` before slicing, so echoing
    the corner the caller asked for would describe an analysis that never
    ran."""
    run = ops.run("grains", _image(_textured()), {"roi": "1,1,999,999"})
    assert _named(run, "region")["rows"] == [[1, 1, 48, 48]]
    assert np.array_equal(
        _labels(run), _labels(ops.run("grains", _image(_textured()), {}))
    ), "a clamped whole-image rectangle is still the whole image"


def test_grains_refuses_two_scopes_at_once() -> None:
    with pytest.raises(ValueError, match="not both"):
        ops.run(
            "grains",
            _image(_textured()),
            {"roi": "1,1,24,24", "region": _rect(0, 0, 23, 23)},
        )


def test_the_grain_table_matches_the_clipped_label_map() -> None:
    """The report is derived from the clipped labels, so the table's row
    count and the map's distinct labels cannot disagree. Clipping after
    the report instead would leave rows describing grains that the region
    removed."""
    run = ops.run(
        "grains",
        _image(_textured()),
        {"region": [{"kind": "ellipse", "bounds": [[4, 4, 40, 40]]}], "method": "gradient"},
    )
    labels = _labels(run)
    distinct = {int(v) for v in labels.ravel() if v != 0}
    assert len(_named(run, "grains")["rows"]) == len(distinct)
    assert _named(run, "n_grains")["value"] == len(distinct)


# ── trained segmentation ─────────────────────────────────────────────


def _scribbled() -> tuple[DataStruct, list[dict[str, Any]]]:
    img = np.zeros((40, 40))
    img[:, 20:] = 40.0
    strokes = [
        {"class_id": 1, "points": [[5, r] for r in range(4, 36)], "radius": 2},
        {"class_id": 2, "points": [[30, r] for r in range(4, 36)], "radius": 2},
    ]
    return _image(img), strokes


def test_train_segment_clips_labels_to_the_region() -> None:
    ds, strokes = _scribbled()
    run = ops.run(
        "train_segment",
        ds,
        {"strokes": strokes, "region": [{"kind": "ellipse", "bounds": [[2, 2, 37, 37]]}]},
    )
    labels = _labels(run)
    assert labels[0, 0] == 0, "outside the ellipse stays background"
    assert _named(run, "region")["exact_mask"] is True


def test_train_preview_keeps_class_ids_and_blanks_the_outside() -> None:
    """`place_values`, not `place_labels`: a preview's numbers are classes."""
    ds, strokes = _scribbled()
    run = ops.run(
        "train_preview",
        ds,
        {"strokes": strokes, "region": [{"kind": "ellipse", "bounds": [[2, 2, 37, 37]]}]},
    )
    classes = np.asarray(_named(run, "class_map")["values"])
    confidence = np.asarray(_named(run, "confidence_map")["values"])
    assert classes[0, 0] == 0 and confidence[0, 0] == 0.0
    assert set(np.unique(classes).tolist()) <= {0, 1, 2}


def test_preview_summaries_are_computed_over_the_selected_pixels() -> None:
    """A clipped map with an unclipped summary is the worst of both.

    `confidence_summary` and the class fractions used to average the whole
    bounding-box prediction while the maps beside them were masked, so a
    reader saw a mean confidence and a class balance that included pixels
    the map visibly does not contain. On this fixture that was 0.968546
    reported against 0.961122 selected, and 0.4198/0.5802 against
    0.3980/0.6020.

    The maps are the oracle: every reported summary has to be
    reproducible from the map the same result carries, which is the
    property that was broken and is not checkable from either half alone.
    """
    ds, strokes = _scribbled()
    bounds = (2.0, 2.0, 37.0, 37.0)
    run = ops.run(
        "train_preview",
        ds,
        {"strokes": strokes, "region": [{"kind": "ellipse", "bounds": [list(bounds)]}]},
    )
    selected = rasterize(
        Region(id="e", parts=(Part(Shape(kind="ellipse", bounds=bounds)),)), (40, 40)
    )
    confidence = np.asarray(_named(run, "confidence_map")["values"])
    classes = np.asarray(_named(run, "class_map")["values"])

    assert _named(run, "mean_confidence")["value"] == pytest.approx(
        float(confidence[selected].mean())
    )
    assert _named(run, "low_confidence_fraction")["value"] == pytest.approx(
        float((confidence[selected] < _named(run, "confidence_threshold")["value"]).mean())
    )
    for class_id, fraction, _boundary in _named(run, "classes")["rows"]:
        assert fraction == pytest.approx(
            float((classes[selected] == class_id).mean())
        ), class_id

    # and the bounding box really does disagree, or the assertions above
    # would hold for an unscoped implementation too
    box = np.zeros((40, 40), dtype=bool)
    box[2:38, 2:38] = True
    assert float(confidence[box].mean()) != pytest.approx(
        float(confidence[selected].mean())
    )


def test_preview_reports_its_region_like_every_other_scoped_consumer() -> None:
    ds, strokes = _scribbled()
    assert not _has(ops.run("train_preview", ds, {"strokes": strokes}), "region")
    run = ops.run(
        "train_preview",
        ds,
        {"strokes": strokes, "region": [{"kind": "ellipse", "bounds": [[2, 2, 37, 37]]}]},
    )
    reported = _named(run, "region")
    assert reported["exact_mask"] is True
    assert reported["label_context"] == "bounding-box"
    assert reported["position_convention"] == "1-based, inclusive, clamped"


def test_preview_class_ids_survive_clipping_unrenumbered() -> None:
    """Classes 2 and 3, with no class 1 anywhere — the shape that tells
    `place_values` apart from `place_labels`.

    Clipping an ellipse clears labelled pixels, so `place_labels` would
    renumber the survivors and hand back classes 1 and 2. Two contiguous
    classes could not show that: renumbering {1,2} yields {1,2} again, so
    the test would pass on the wrong function.
    """
    img = np.zeros((40, 40))
    img[:, 20:] = 40.0
    ds = _image(img)
    strokes = [
        {"class_id": 2, "points": [[5, r] for r in range(4, 36)], "radius": 2},
        {"class_id": 3, "points": [[30, r] for r in range(4, 36)], "radius": 2},
    ]
    run = ops.run(
        "train_preview",
        ds,
        {"strokes": strokes, "region": [{"kind": "ellipse", "bounds": [[2, 2, 37, 37]]}]},
    )
    present = set(np.unique(np.asarray(_named(run, "class_map")["values"])).tolist())
    assert 3 in present, "class 3 must stay class 3, not slide down to 2"
    assert present <= {0, 2, 3}


def test_a_stroke_outside_the_region_does_not_train_the_model() -> None:
    """A stroke is a claim about the specimen being analyzed; the region
    says which specimen that is. Adding a contradictory stroke outside the
    region must leave the answer untouched."""
    ds, strokes = _scribbled()
    # An ELLIPSE, so "outside the region" and "outside the crop" differ: a
    # rect region would drop the extra stroke by slicing alone, and the
    # test would pass without the mask ever being consulted.
    region = [{"kind": "ellipse", "bounds": [[0, 0, 39, 39]]}]
    honest = ops.run("train_preview", ds, {"strokes": strokes, "region": region})
    misleading = ops.run(
        "train_preview",
        ds,
        {
            "strokes": [
                *strokes,
                # a bounding-box CORNER — inside the crop, outside the
                # ellipse — and deliberately contradicting class 2
                {"class_id": 1, "points": [[c, 1] for c in range(30, 39)], "radius": 1},
            ],
            "region": region,
        },
    )
    assert np.array_equal(
        np.asarray(_named(honest, "class_map")["values"]),
        np.asarray(_named(misleading, "class_map")["values"]),
    )


# ── bounded memory ───────────────────────────────────────────────────


def test_the_segmenter_receives_the_crop_not_the_whole_raster() -> None:
    """The mechanism that makes a region-scoped run cheap, asserted
    directly rather than through a memory proxy.

    A proxy would not work here: the op's `map` envelope calls `.tolist()`
    on a full-image label array, and that Python list dwarfs every array
    in the computation (~71 MB for 2048x2048, measured, scoped or not).
    That cost is pre-existing and full-image by definition, so peak memory
    cannot show whether the ANALYSIS was cropped. The shape handed to
    `particle_analysis` can, and it is the thing actually being claimed.
    """
    seen: list[tuple[int, ...]] = []
    real = catalogue_structure.particle_analysis

    def spy(img: np.ndarray, **kw: Any) -> Any:
        seen.append(np.shape(img))
        return real(img, **kw)

    big = np.zeros((512, 512))
    big[100:140, 100:140] = 10.0
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(catalogue_structure, "particle_analysis", spy)
        run = ops.run(
            "particles",
            _image(big),
            {"region": [{"kind": "ellipse", "bounds": [[90, 90, 150, 150]]}]},
        )
    finally:
        monkey.undo()

    assert seen == [(61, 61)], "the segmenter must see the bounding box, not 512x512"
    assert _named(run, "n_particles")["value"] == 1
    assert _labels(run).shape == (512, 512), "while the map stays full-image"


def test_region_values_does_not_copy_the_raster() -> None:
    """Where the memory claim is real: pulling the selected pixels out of
    a big raster costs the SELECTION, not the raster. `values[mask]` over
    a full-image boolean would allocate one element per selected pixel —
    fine — but casting or copying the raster first would not.
    """
    tracemalloc.start()
    try:
        probe = np.empty(2_000_000, dtype=np.float64)  # 16 MB
        _, probe_peak = tracemalloc.get_traced_memory()
        del probe
        if probe_peak < 8_000_000:  # pragma: no cover - platform dependent
            pytest.skip("tracemalloc does not observe numpy data allocations here")

        big = np.ones((2048, 2048), dtype=np.float64)  # 33.6 MB
        mask = np.zeros((2048, 2048), dtype=bool)
        mask[100:140, 100:140] = True
        mask[120, 120] = False  # irregular, so the fast rect path cannot apply

        before, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        got = region_values(big, (101, 101, 140, 140), mask)
        _, peak = tracemalloc.get_traced_memory()
        overhead = peak - before
    finally:
        tracemalloc.stop()

    assert got.size == 40 * 40 - 1
    assert overhead < big.nbytes // 8, (
        f"allocated {overhead / 1e6:.1f} MB to read {got.size} pixels out of a "
        f"{big.nbytes / 1e6:.1f} MB raster"
    )
