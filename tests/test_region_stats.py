"""Imaging statistics over canonical regions — roadmap 4C-2.

`calc.region_stats.region_stats` is the one place a region becomes
mean/std/min/max, shared by `/measure/roi`, the `image_stats` op and
`profile_stats.roi_stats`.

## Where the expected answers come from

`stats_over` below computes the expected numbers with Python's own
`statistics` module over an explicitly built pixel list — a different
implementation, not a second spelling of the one under test. NumPy is used
only to hold the image. That matters more here than in earlier waves,
because `region_stats` and its oracle would otherwise both be `np.mean`
calls and would agree on any shared misunderstanding of which pixels are
in scope.

The rectangular-parity tests take their expected answer from a third
place: `roi_stats` as it behaved BEFORE this wave, transcribed into
`legacy_roi_stats`. If the migration changed a published number, that
comparison says so directly rather than leaving it to be noticed later.

## The two conventions this wave deliberately did NOT unify

`roi_stats` reports MATLAB's sample std (ddof=1); the `image_stats` op
reports the population std (ddof=0). Both are pinned here. 4C converges
which PIXELS an analysis reads, not which estimator it publishes, and
silently switching either would change numbers users already have.
"""

from __future__ import annotations

import statistics
import tracemalloc

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.profile_stats import roi_stats
from fermiviewer.calc.region_mask import rasterize
from fermiviewer.calc.region_stats import STD_MATLAB, STD_POPULATION, region_stats
from fermiviewer.calc.regions import Part, Region, ellipse, rect
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.regions_model import RegionSet
from fermiviewer.project_session import project
from fermiviewer.server import create_app
from fermiviewer.session import store

H, W = 12, 14


def an_image(seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(100.0, 20.0, size=(H, W))


def stats_over(img, pixels, *, pixel_size=float("nan"), ddof=1) -> dict:
    """The oracle: pure-Python statistics over an explicit pixel list.

    Deliberately NOT numpy — `statistics.fmean`/`stdev` are a separate
    implementation, so agreeing with them is evidence rather than a
    tautology. Non-finite pixels are dropped, matching the contract.
    """
    vals = [float(img[r, c]) for r, c in sorted(pixels)]
    finite = [v for v in vals if np.isfinite(v)]
    area = (
        len(vals) * pixel_size**2 if np.isfinite(pixel_size) else float(len(vals))
    )
    out = {"n_pixels": float(len(vals)), "n_finite": float(len(finite)), "area": area}
    if not finite:
        return {**out, "mean": float("nan"), "std": float("nan"),
                "min": float("nan"), "max": float("nan")}
    if len(finite) > ddof:
        std = statistics.stdev(finite) if ddof == 1 else statistics.pstdev(finite)
    else:
        std = 0.0
    return {**out, "mean": statistics.fmean(finite), "std": std,
            "min": min(finite), "max": max(finite)}


def rect_pixels(r1, c1, r2, c2) -> set:
    """1-based INCLUSIVE rect, clamped, straight from the definition."""
    return {
        (r, c)
        for r in range(H)
        for c in range(W)
        if r1 - 1 <= r <= r2 - 1 and c1 - 1 <= c <= c2 - 1
    }


def mask_pixels(mask: np.ndarray) -> set:
    return {(int(r), int(c)) for r, c in zip(*np.nonzero(mask), strict=True)}


def same(got: dict, want: dict) -> bool:
    return all(
        (np.isnan(got[k]) and np.isnan(want[k])) or np.isclose(got[k], want[k])
        for k in want
    )


# ── rectangular parity: the migration must not move a number ─────────


def legacy_roi_stats(img, row1, col1, row2, col2, pixel_size, shape):
    """`roi_stats` exactly as it was before 4C-2, transcribed. The parity
    baseline: an independent copy, so it cannot drift with the code."""
    arr = np.asarray(img, dtype=np.float64)
    h, w = arr.shape
    r1, r2 = sorted((int(round(row1)), int(round(row2))))
    c1, c2 = sorted((int(round(col1)), int(round(col2))))
    r1, r2 = max(r1, 1), min(r2, h)
    c1, c2 = max(c1, 1), min(c2, w)
    if r1 > r2 or c1 > c2:
        raise ValueError("ROI is empty after clamping to the image")
    sel = arr[r1 - 1:r2, c1 - 1:c2]
    if shape == "ellipse":
        sh, sw = sel.shape
        cy, cx = (sh - 1) / 2, (sw - 1) / 2
        ry, rx = max(sh / 2, 0.5), max(sw / 2, 0.5)
        yy = (np.arange(sh)[:, None] - cy) / ry
        xx = (np.arange(sw)[None, :] - cx) / rx
        sel = sel[yy**2 + xx**2 <= 1.0]
    area_px = float(sel.size)
    return {
        "mean": float(sel.mean()),
        "std": float(sel.std(ddof=1)) if sel.size > 1 else 0.0,
        "min": float(sel.min()),
        "max": float(sel.max()),
        "n_pixels": area_px,
        "area": area_px * pixel_size**2 if np.isfinite(pixel_size) else area_px,
    }


RECTS = [
    (1, 1, H, W),        # whole image
    (3, 4, 9, 11),       # interior
    (5, 5, 5, 5),        # one pixel — std must be 0, not a ddof blow-up
    (2, 2, 2, 9),        # one row
    (4, 4, 11, 4),       # one column
    (0, 0, 99, 99),      # clamped
]


@pytest.mark.parametrize("r", RECTS)
@pytest.mark.parametrize("shape", ["rect", "ellipse"])
def test_roi_stats_reports_exactly_what_it_reported_before(r, shape) -> None:
    """Rectangular AND elliptical parity, on a finite image where the old
    and new NaN policies cannot differ."""
    img = an_image()
    old = legacy_roi_stats(img, *r, pixel_size=0.5, shape=shape)
    new = roi_stats(img, *r, pixel_size=0.5, shape=shape)
    assert same(new, old), f"{shape}{r}: {new} != {old}"


@pytest.mark.parametrize("r", RECTS)
def test_a_rect_agrees_with_the_independent_oracle(r) -> None:
    """Parity with the old code is not enough — both could be wrong the
    same way. This checks against pure-Python statistics."""
    img = an_image()
    got = region_stats(img, _clamp(r), pixel_size=0.25, ddof=STD_MATLAB)
    want = stats_over(img, rect_pixels(*_clamp(r)), pixel_size=0.25, ddof=1)
    assert same(got, want)


def _clamp(r) -> tuple[int, int, int, int]:
    r1, c1, r2, c2 = r
    r1, r2 = sorted((r1, r2))
    c1, c2 = sorted((c1, c2))
    return max(r1, 1), max(c1, 1), min(r2, H), min(c2, W)


def test_the_canonical_ellipse_is_pixel_identical_to_the_inline_one() -> None:
    """4A defined `ellipse`'s semi-axis as the footprint (extent+1)/2
    specifically to match `roi_stats`' `ry = sh/2`. `roi_stats` now routes
    through the primitive, so that claim is load-bearing rather than
    decorative — this is what makes the migration behaviour-preserving."""
    for r1, c1, r2, c2 in RECTS:
        r1, c1, r2, c2 = _clamp((r1, c1, r2, c2))
        canonical = rasterize(
            Region(id="e", parts=(Part(ellipse(r1 - 1, c1 - 1, r2 - 1, c2 - 1)),)),
            (H, W),
        )
        sh, sw = r2 - r1 + 1, c2 - c1 + 1
        cy, cx = (sh - 1) / 2, (sw - 1) / 2
        ry, rx = max(sh / 2, 0.5), max(sw / 2, 0.5)
        yy = (np.arange(sh)[:, None] - cy) / ry
        xx = (np.arange(sw)[None, :] - cx) / rx
        legacy = np.zeros((H, W), dtype=bool)
        legacy[r1 - 1:r2, c1 - 1:c2] = yy**2 + xx**2 <= 1.0
        assert np.array_equal(canonical, legacy), f"({r1},{c1},{r2},{c2})"


# ── irregular masks, holes, disconnected regions ─────────────────────


def stats_of_region(img, region: Region, **kw) -> tuple[dict, set]:
    mask = rasterize(region, (H, W))
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    box = (int(rows[0]) + 1, int(cols[0]) + 1, int(rows[-1]) + 1, int(cols[-1]) + 1)
    return region_stats(img, box, mask, **kw), mask_pixels(mask)


def test_an_irregular_mask_measures_only_its_own_pixels() -> None:
    img = an_image()
    got, pixels = stats_of_region(
        img, Region(id="e", parts=(Part(ellipse(2, 3, 9, 10)),)), ddof=STD_MATLAB
    )
    assert same(got, stats_over(img, pixels, ddof=1))


def test_an_irregular_mask_differs_from_its_bounding_rectangle() -> None:
    """The reason 4C-2 exists. If these agreed the mask would be
    decorative and every other test here would still pass."""
    img = an_image()
    region = Region(id="e", parts=(Part(ellipse(2, 3, 9, 10)),))
    exact, pixels = stats_of_region(img, region, ddof=STD_MATLAB)
    boxed = region_stats(img, (3, 4, 10, 11), ddof=STD_MATLAB)
    assert exact["n_pixels"] < boxed["n_pixels"]
    assert exact["mean"] != boxed["mean"]


def test_a_hole_is_excluded_from_the_statistics() -> None:
    """An `exclude` part must remove pixels from the aggregate, not merely
    shrink the bounding box."""
    img = an_image()
    region = Region(
        id="ring",
        parts=(Part(rect(1, 1, 8, 8)), Part(rect(3, 3, 5, 5), mode="exclude")),
    )
    got, pixels = stats_of_region(img, region, ddof=STD_MATLAB)
    expected = rect_pixels(2, 2, 9, 9) - rect_pixels(4, 4, 6, 6)
    assert pixels == {(r - 1, c - 1) for r, c in _one_based(expected)}
    assert same(got, stats_over(img, pixels, ddof=1))
    assert got["n_pixels"] == 8 * 8 - 3 * 3


def _one_based(pixels) -> set:
    return {(r + 1, c + 1) for r, c in pixels}


def test_disconnected_blobs_are_one_measurement() -> None:
    """Two separate pieces of specimen are one region — and the bounding
    box spans the gap, so the mask is what keeps the gap out."""
    img = an_image()
    region = Region(
        id="two", parts=(Part(rect(0, 0, 2, 2)), Part(rect(8, 9, 10, 12)))
    )
    got, pixels = stats_of_region(img, region, ddof=STD_MATLAB)
    assert got["n_pixels"] == 3 * 3 + 3 * 4
    assert same(got, stats_over(img, pixels, ddof=1))
    boxed = region_stats(img, (1, 1, 11, 13), ddof=STD_MATLAB)
    assert boxed["n_pixels"] > got["n_pixels"], "the box spans the gap"


# ── NaN handling ─────────────────────────────────────────────────────


def test_non_finite_pixels_are_counted_but_not_averaged() -> None:
    """A dead detector pixel occupies specimen area but has no value, so
    it counts toward `n_pixels` and `area` and is absent from `n_finite`
    and from every aggregate."""
    img = an_image()
    img[4, 5] = np.nan
    img[6, 7] = np.inf
    got = region_stats(img, (1, 1, H, W), pixel_size=2.0, ddof=STD_MATLAB)
    assert got["n_pixels"] == H * W
    assert got["n_finite"] == H * W - 2
    assert got["area"] == H * W * 4.0, "area follows n_pixels, not n_finite"
    assert same(got, stats_over(img, rect_pixels(1, 1, H, W), pixel_size=2.0, ddof=1))
    assert np.isfinite(got["mean"]) and np.isfinite(got["max"])


def test_an_all_nan_region_reports_nan_rather_than_raising() -> None:
    """An all-dead region is a real thing to measure; saying so keeps the
    `n_pixels` the caller asked for, which raising would throw away."""
    img = np.full((H, W), np.nan)
    got = region_stats(img, (2, 2, 4, 4), pixel_size=1.0, ddof=STD_MATLAB)
    assert got["n_pixels"] == 9.0 and got["n_finite"] == 0.0
    assert all(np.isnan(got[k]) for k in ("mean", "std", "min", "max"))
    assert got["area"] == 9.0


def test_roi_stats_no_longer_lets_one_nan_poison_the_roi() -> None:
    """The one deliberate behaviour change in this wave, pinned so it is
    visible: `roi_stats` used to return NaN for the whole ROI if a single
    pixel was NaN. It now reports the finite pixels and says how many."""
    img = an_image()
    img[5, 5] = np.nan
    old = legacy_roi_stats(img, 1, 1, H, W, pixel_size=float("nan"), shape="rect")
    new = roi_stats(img, 1, 1, H, W, pixel_size=float("nan"))
    assert np.isnan(old["mean"]), "the old behaviour really did propagate"
    assert np.isfinite(new["mean"])
    assert new["n_finite"] == H * W - 1
    assert new["n_pixels"] == H * W


# ── the two std conventions, both pinned ─────────────────────────────


def test_the_two_std_conventions_stay_distinct() -> None:
    """Neither consumer's estimator was switched. If a later change
    unifies them, this fails and forces the decision to be explicit."""
    img = an_image()
    sample = region_stats(img, (1, 1, H, W), ddof=STD_MATLAB)["std"]
    population = region_stats(img, (1, 1, H, W), ddof=STD_POPULATION)["std"]
    assert sample != population
    pixels = rect_pixels(1, 1, H, W)
    assert np.isclose(sample, stats_over(img, pixels, ddof=1)["std"])
    assert np.isclose(population, stats_over(img, pixels, ddof=0)["std"])


def test_a_single_pixel_has_zero_std_not_a_ddof_blow_up() -> None:
    """MATLAB's std() of a scalar is 0, and roi_stats has always matched."""
    img = an_image()
    assert region_stats(img, (5, 5, 5, 5), ddof=STD_MATLAB)["std"] == 0.0
    assert roi_stats(img, 5, 5, 5, 5)["std"] == 0.0


# ── calibration ──────────────────────────────────────────────────────


@pytest.mark.parametrize("px, expect", [(0.5, 0.25), (2.0, 4.0), (1.0, 1.0)])
def test_physical_area_scales_with_the_square_of_the_pixel_size(px, expect) -> None:
    got = region_stats(an_image(), (2, 2, 4, 4), pixel_size=px)
    assert got["n_pixels"] == 9.0
    assert np.isclose(got["area"], 9.0 * expect)


def test_an_uncalibrated_image_reports_area_in_pixels() -> None:
    got = region_stats(an_image(), (2, 2, 4, 4), pixel_size=float("nan"))
    assert got["area"] == got["n_pixels"] == 9.0


# ── refusals ─────────────────────────────────────────────────────────


def test_a_region_selecting_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="no pixels"):
        region_stats(an_image(), (1, 1, H, W), np.zeros((H, W), dtype=bool))


def test_a_mask_that_is_not_full_image_is_refused() -> None:
    """Same trap as 4C-1: a crop-local mask slices to the right shape when
    the rect starts at the top-left, so the check must be against the
    IMAGE."""
    with pytest.raises(ValueError, match="full-image"):
        region_stats(an_image(), (1, 1, 4, 4), np.ones((4, 4), dtype=bool))


@pytest.mark.parametrize("dtype", [np.int64, np.uint8, np.float64])
def test_a_non_boolean_mask_is_refused(dtype) -> None:
    with pytest.raises(ValueError, match="boolean"):
        region_stats(an_image(), (1, 1, 4, 4), np.ones((H, W), dtype=dtype))


def test_a_non_2d_raster_is_refused() -> None:
    with pytest.raises(ValueError, match="2-D"):
        region_stats(np.zeros((4, 4, 3)), (1, 1, 4, 4))


# ── bounded memory ───────────────────────────────────────────────────


def test_region_stats_does_not_copy_the_raster_in_float64() -> None:
    """`roi_stats` used to cast the whole image to float64 and then, for
    an ellipse, fancy-index a copy of the selection on top.

    The budget is the RASTER'S OWN SIZE, not zero, and the difference is
    the point. Two boolean arrays are unavoidable here — `np.isfinite` of
    the region, intersected in place with the caller's mask — so a
    tighter bound would be unsatisfiable no matter how the aggregates are
    written. What must never happen is an allocation that scales with the
    raster in float64: the obvious one-line
    `np.std(view, where=usable, dtype=np.float64)` allocates exactly that
    (33.6 MB here, measured), and it is what `_masked_std`'s chunking
    avoids. This budget fails on that and passes on the masks.

    numpy reports its data allocations to tracemalloc (same technique as
    tests/test_eds_maps.py)."""
    tracemalloc.start()
    try:
        probe = np.empty(2_000_000, dtype=np.float64)  # 16 MB
        _, probe_peak = tracemalloc.get_traced_memory()
        del probe
        if probe_peak < 8_000_000:  # pragma: no cover - platform dependent
            pytest.skip("tracemalloc does not observe numpy data allocations here")

        big = np.ones((2048, 2048), dtype=np.float32)  # 16 MB
        mask = np.ones((2048, 2048), dtype=bool)
        mask[0, 0] = False  # broad and irregular: worst case for a copy
        a_float64_copy = big.size * 8       # 33.6 MB — the thing to avoid
        budget = big.nbytes                  # 16.8 MB — the raster itself

        before, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        got = region_stats(big, (1, 1, 2048, 2048), mask)
        _, peak = tracemalloc.get_traced_memory()
        overhead = peak - before
    finally:
        tracemalloc.stop()

    assert got["n_pixels"] == 2048 * 2048 - 1
    assert budget < a_float64_copy, "the budget has to exclude a float64 copy"
    assert overhead < budget, (
        f"allocated {overhead / 1e6:.1f} MB, over the {budget / 1e6:.1f} MB "
        f"raster itself; a float64 copy would be {a_float64_copy / 1e6:.1f} MB"
    )


# ── the HTTP surface ─────────────────────────────────────────────────


@pytest.fixture()
def client():
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


def load_image(img_id: str = "img1", data=None) -> np.ndarray:
    img = an_image() if data is None else data
    store.restore(
        img_id,
        DataStruct(
            data=img,
            kind=DataKind.IMAGE,
            axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        ),
        "frame.tif",
    )
    return img


def put_region(region: Region, image_id="img1") -> None:
    project.replace_regions(
        (RegionSet(id="s1", regions=(region,), image_id=image_id),), ()
    )


def measure(client, **body) -> dict:
    resp = client.post("/api/measure/roi", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_route_rect_path_is_unchanged(client) -> None:
    img = load_image()
    got = measure(client, image_id="img1", rect=[3, 4, 9, 11])
    want = legacy_roi_stats(img, 3, 4, 9, 11, pixel_size=0.5, shape="rect")
    assert same(got, want)
    assert got["unit"] == "nm"


def test_the_route_measures_a_named_region_exactly(client) -> None:
    img = load_image()
    region = Region(id="e", parts=(Part(ellipse(2, 3, 9, 10)),))
    put_region(region)
    got = measure(client, image_id="img1", region_ref="s1/e")
    pixels = mask_pixels(rasterize(region, (H, W)))
    assert same(got, stats_over(img, pixels, pixel_size=0.5, ddof=1))
    assert got["exact_mask"] is True
    assert got["region"] == [3, 4, 10, 11]


def test_a_rect_region_through_the_route_matches_the_legacy_rect(client) -> None:
    """The migration's promise at the HTTP boundary."""
    load_image()
    put_region(Region(id="r", parts=(Part(rect(2, 3, 8, 10)),)))
    named = measure(client, image_id="img1", region_ref="s1/r")
    legacy = measure(client, image_id="img1", rect=[3, 4, 9, 11])
    for k in ("mean", "std", "min", "max", "n_pixels", "area"):
        assert np.isclose(named[k], legacy[k]), k
    assert named["exact_mask"] is False


@pytest.mark.parametrize(
    "body, why",
    [
        ({"rect": [1, 1, 4, 4], "region_ref": "s1/r"}, "not both"),
        ({}, "not both"),
        ({"region_ref": "s1/r", "shape": "ellipse"}, "carries its own geometry"),
        ({"region_ref": "s1/r", "shape": "rect"}, "carries its own geometry"),
    ],
    ids=["both", "neither", "shape-ellipse", "shape-rect"],
)
def test_scope_parameters_are_never_silently_discarded(client, body, why) -> None:
    """The 4C-1 review's lesson applied up front: a param the caller
    believed in must not be dropped. `shape` alongside `region_ref` is the
    subtle one — the region carries its own geometry, so the shape would
    vanish."""
    load_image()
    put_region(Region(id="r", parts=(Part(rect(1, 1, 4, 4)),)))
    resp = client.post("/api/measure/roi", json={"image_id": "img1", **body})
    assert resp.status_code == 422, resp.text
    assert why in resp.text


def test_a_region_drawn_on_another_image_is_refused(client) -> None:
    load_image("img1")
    load_image("img2")
    put_region(Region(id="r", parts=(Part(rect(1, 1, 4, 4)),)), image_id="img1")
    resp = client.post(
        "/api/measure/roi", json={"image_id": "img2", "region_ref": "s1/r"}
    )
    assert resp.status_code == 422
    assert "drawn on image" in resp.text


# ── the image_stats op keeps its own convention ──────────────────────


def test_the_image_stats_op_still_reports_the_population_std(client) -> None:
    """Migrated to region_stats but NOT switched to ddof=1."""
    from fermiviewer.ops.registry import run

    img = an_image()
    img[3, 3] = np.nan
    load_image("img1", img)
    value = run("image_stats", store.get("img1")).value
    pixels = rect_pixels(1, 1, H, W)
    want = stats_over(img, pixels, ddof=0)
    for k in ("mean", "std", "min", "max"):
        assert np.isclose(value[k], want[k]), k
    assert value["n_finite"] == H * W - 1
    assert value["shape"] == [H, W]


# ── the #189 compatibility re-exports ────────────────────────────────


@pytest.mark.parametrize("name", ["rasterize", "bounding_box", "to_rect_roi"])
def test_the_pre_189_import_path_still_works(name) -> None:
    """#189 moved these into `calc/region_mask.py`. fermiviewer is
    published, so a public symbol that simply vanishes breaks code we
    cannot see; the old path resolves to the same object."""
    import fermiviewer.calc.region_mask as region_mask
    import fermiviewer.calc.regions as regions

    assert getattr(regions, name) is getattr(region_mask, name)
    assert name in regions.__all__


def test_the_re_exports_do_not_shadow_a_real_attribute_error() -> None:
    with pytest.raises(AttributeError, match="no attribute 'nonexistent'"):
        import fermiviewer.calc.regions as regions

        _ = regions.nonexistent


def test_a_star_import_from_calc_regions_carries_the_moved_names() -> None:
    """`__all__` drives `import *`, so the compatibility promise has to
    cover that spelling too."""
    namespace: dict = {}
    exec("from fermiviewer.calc.regions import *", namespace)  # noqa: S102
    for name in ("rasterize", "bounding_box", "to_rect_roi", "rect", "Region"):
        assert name in namespace, name
