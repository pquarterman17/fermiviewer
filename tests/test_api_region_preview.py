"""4D — what an analysis would read, asked before it reads it.

The property that matters is AGREEMENT: a preview computed by a second
code path is a preview of something else, which is worse than no preview
at all. So the tests below do not check the numbers against hand-counted
constants alone — they check them against what the analysis routes
actually report over the same region.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.project_session import project
from fermiviewer.server import create_app
from fermiviewer.session import store

pytestmark = pytest.mark.api


@pytest.fixture()
def client():
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


def _image(pixel_size: float = float("nan"), unit: str = "") -> str:
    """A NON-SQUARE image, so a row/col transposition cannot pass."""
    rng = np.random.default_rng(0)
    ds = DataStruct(
        data=rng.normal(100.0, 5.0, (40, 60)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(scale=pixel_size, units=unit), AxisCal(scale=pixel_size, units=unit)),
        metadata={},
    )
    return store.add_parsed(ds, "specimen.dm4")


#: A 10x20 rect with a 4x4 bite taken out — irregular, so `is_exact` is
#: true and the bounding box overstates the scope.
HOLED = {
    "schema": 1,
    "classes": [],
    "sets": [
        {
            "id": "picked",
            "name": None,
            "image_id": None,
            "meta": {},
            "regions": [
                {
                    "id": "r1",
                    "name": None,
                    "region_class": None,
                    "meta": {},
                    "parts": [
                        {"mode": "include", "shape": {"kind": "rect", "bounds": [5, 5, 14, 24]}},
                        {"mode": "exclude", "shape": {"kind": "rect", "bounds": [7, 7, 10, 10]}},
                    ],
                }
            ],
        }
    ],
}


def _install(client: TestClient) -> None:
    assert client.post("/api/region-sets/replace", json=HOLED).status_code == 200


def _preview(client: TestClient, image_id: str, **kw) -> dict:
    r = client.post(
        "/api/regions/preview", json={"image_id": image_id, **kw}
    )
    assert r.status_code == 200, r.text
    return r.json()


# ── the summary agrees with the analysis ─────────────────────────────


def test_the_preview_counts_the_pixels_the_analysis_reads(client) -> None:
    """The load-bearing property. `/measure/roi` reports `n_pixels` over
    the same region through `calc.region_stats`; the preview must arrive
    at the same number by resolving the same reference, or it is
    describing a scope nobody will analyse."""
    image_id = _image()
    _install(client)
    preview = _preview(client, image_id, region_ref="picked")

    measured = client.post(
        "/api/measure/roi", json={"image_id": image_id, "region_ref": "picked"}
    )
    assert measured.status_code == 200, measured.text
    assert preview["pixel_count"] == int(measured.json()["n_pixels"])


def test_an_irregular_region_reports_a_scope_narrower_than_its_box(client) -> None:
    """The number the summary exists to surface: 10x20 minus a 4x4 bite
    is 200 - 16 = 184 pixels inside a 200-pixel box. A preview that
    showed only the bounding box would overstate the work by the size of
    the hole, which is exactly what a user checking scope needs to see.
    """
    image_id = _image()
    _install(client)
    preview = _preview(client, image_id, region_ref="picked")
    assert preview["pixel_count"] == 184
    assert preview["bbox_pixels"] == 200
    assert preview["exact_mask"] is True
    # The region's own bounds are 0-based inclusive (`calc/regions.py`);
    # `rect` is `calc.roi.RectRoi`, 1-based inclusive. So [5,5,14,24]
    # becomes (6,6,15,25) — asserted rather than copied from the input,
    # because a preview reporting the region's raw bounds would be off by
    # one against every analysis that consumes the rect.
    assert preview["rect"] == [6, 6, 15, 25]


def test_a_plain_rectangle_is_not_exact_and_fills_its_box(client) -> None:
    """`is_exact` means "narrower than the box". A rect is its own box, so
    reporting True here would tell a reader a hole exists where none
    does."""
    preview = _preview(client, _image(), roi="3,4,12,20")
    assert preview["exact_mask"] is False
    assert preview["pixel_count"] == preview["bbox_pixels"] == 10 * 17


def test_no_scope_at_all_previews_the_whole_image(client) -> None:
    """An unscoped analysis reads every pixel, and being able to compare
    a region against that is the point of `fraction`."""
    preview = _preview(client, _image())
    assert preview["pixel_count"] == preview["image_pixels"] == 40 * 60
    assert preview["fraction"] == 1.0
    # The RECT, not just the count: 40*60 and 60*40 are the same product,
    # so a transposed grid is invisible to every other assertion here —
    # and to any region small enough to fit both orientations. This is
    # the one place the row/col order is pinned.
    assert preview["rect"] == [1, 1, 40, 60]


def test_the_fraction_is_of_the_whole_image(client) -> None:
    image_id = _image()
    _install(client)
    preview = _preview(client, image_id, region_ref="picked")
    assert preview["fraction"] == pytest.approx(184 / 2400)


# ── calibration is present or absent, never ambiguous ────────────────


def test_physical_area_uses_the_pixel_size(client) -> None:
    """184 pixels at 0.5 nm/px is 184 * 0.25 nm^2. `unit` is the LENGTH
    unit, matching `/regions/propose`, so the area is in unit^2."""
    image_id = _image(pixel_size=0.5, unit="nm")
    _install(client)
    preview = _preview(client, image_id, region_ref="picked")
    assert preview["area_calibrated"] == pytest.approx(184 * 0.25)
    assert preview["unit"] == "nm"


def test_an_uncalibrated_image_reports_no_area_rather_than_a_count(client) -> None:
    """ADR 0004's rule, at the one place it is tempting to break: an
    uncalibrated area is ABSENT, not the pixel count wearing an area's
    name. `calc.region_stats` does return the count there, which is why
    this route computes its own — a number whose unit silently changes is
    worse than one that admits it is unknown."""
    image_id = _image()
    _install(client)
    preview = _preview(client, image_id, region_ref="picked")
    assert preview["area_calibrated"] is None
    assert preview["unit"] == "px"
    assert preview["pixel_count"] == 184, "the count is still reported"


# ── refusals, shared with the analyses ───────────────────────────────


def test_a_region_selecting_nothing_is_refused_not_reported_as_zero(client) -> None:
    """Nothing to analyse is an answer the caller must handle, not a
    measurement of zero — the same refusal every 4C consumer makes."""
    empty = {
        "schema": 1,
        "classes": [],
        "sets": [
            {
                "id": "off", "name": None, "image_id": None, "meta": {},
                "regions": [
                    {
                        "id": "r1", "name": None, "region_class": None, "meta": {},
                        "parts": [
                            {
                                "mode": "include",
                                "shape": {"kind": "rect", "bounds": [500, 500, 520, 520]},
                            }
                        ],
                    }
                ],
            }
        ],
    }
    assert client.post("/api/region-sets/replace", json=empty).status_code == 200
    r = client.post(
        "/api/regions/preview", json={"image_id": _image(), "region_ref": "off"}
    )
    assert r.status_code == 422


def test_two_scopes_at_once_is_refused(client) -> None:
    """ADR 0007 §5, reached through the route rather than restated in it."""
    image_id = _image()
    _install(client)
    r = client.post(
        "/api/regions/preview",
        json={"image_id": image_id, "region_ref": "picked", "roi": "1,1,5,5"},
    )
    assert r.status_code == 422
    # The REASON is asserted, not just the status. A malformed roi, an
    # unresolvable reference and this all return 422, so a bare status
    # check passes for the wrong reason — which is how a test stops
    # testing what its name says.
    assert "not both" in r.json()["detail"]


def test_a_set_drawn_on_another_image_is_refused(client) -> None:
    """ADR 0007 §6. Previewing a region against the wrong specimen would
    report a scope the analysis would then refuse, which is the worst
    kind of preview: one that disagrees with the run."""
    bound = {
        "schema": 1, "classes": [],
        "sets": [{
            "id": "picked", "name": None, "image_id": "some-other-image", "meta": {},
            "regions": [{
                "id": "r1", "name": None, "region_class": None, "meta": {},
                "parts": [{"mode": "include", "shape": {"kind": "rect", "bounds": [5, 5, 14, 24]}}],
            }],
        }],
    }
    assert client.post("/api/region-sets/replace", json=bound).status_code == 200
    r = client.post(
        "/api/regions/preview", json={"image_id": _image(), "region_ref": "picked"}
    )
    assert r.status_code == 422
    assert "drawn on image" in r.json()["detail"]


def test_unknown_image_and_unknown_reference(client) -> None:
    assert client.post(
        "/api/regions/preview", json={"image_id": "nope", "region_ref": "picked"}
    ).status_code == 404
    unknown = client.post(
        "/api/regions/preview", json={"image_id": _image(), "region_ref": "ghost"}
    )
    assert unknown.status_code == 422
    assert "unknown region set 'ghost'" in unknown.json()["detail"]


def test_the_preview_carries_the_resolver_s_own_provenance(client) -> None:
    """The preview must say what it resolved, not just how big it is.

    A scope summary a user cannot trace back to a reference is a number
    with no subject — and this is the resolver's own record, passed
    through rather than rebuilt, so it cannot describe a different
    resolution than the one measured. `frame` travels with it because a
    rect means nothing without its index base and bounds convention.
    """
    image_id = _image()
    _install(client)
    prov = _preview(client, image_id, region_ref="picked")["provenance"]
    assert prov["source"] == "region-set"
    assert prov["set_id"] == "picked"
    assert prov["region_ids"] == ["r1"]
    assert prov["exact_mask"] is True
    assert prov["rect"] == [6, 6, 15, 25]
    assert prov["frame"]["index_base"] == 1
    assert prov["frame"]["bounds"] == "inclusive"


@pytest.mark.parametrize(
    ("kw", "source"),
    [({"roi": "3,4,12,20"}, "roi"), ({}, "whole-image")],
)
def test_every_scope_says_which_kind_it_is(client, kw: dict, source: str) -> None:
    """A rect and an unscoped run are distinguishable in the record, so a
    reader can tell "the whole image" from "a rect that happens to cover
    it" — the two are the same pixels and different intentions."""
    prov = _preview(client, _image(), **kw)["provenance"]
    assert prov["source"] == source
    assert prov["exact_mask"] is False


# ── a set is a union, and that is the number reported ────────────────


def _two_regions(a: list[int], b: list[int]) -> dict:
    return {
        "schema": 1,
        "classes": [],
        "sets": [
            {
                "id": "picked", "name": None, "image_id": None, "meta": {},
                "regions": [
                    {
                        "id": f"r{i}", "name": None, "region_class": None, "meta": {},
                        "parts": [
                            {"mode": "include", "shape": {"kind": "rect", "bounds": bounds}}
                        ],
                    }
                    for i, bounds in enumerate((a, b))
                ],
            }
        ],
    }


def test_overlapping_regions_are_counted_once(client) -> None:
    """ADR 0007 §7 makes a whole-set reference a UNION, and the preview
    reports the union — 175 pixels for two overlapping 10x10s, not the
    200 a sum would give. Getting this wrong would overstate the work by
    the overlap, and the summary exists to be trusted on exactly this."""
    assert client.post(
        "/api/region-sets/replace", json=_two_regions([0, 0, 9, 9], [5, 5, 14, 14])
    ).status_code == 200
    preview = _preview(client, _image(), region_ref="picked")
    assert preview["pixel_count"] == 175


def test_disjoint_regions_show_a_box_far_larger_than_the_scope(client) -> None:
    """The clearest case for reporting both numbers: two 4x4 squares at
    opposite corners are 32 pixels inside a 196-pixel bounding box. A
    preview showing only the box would overstate the work six-fold."""
    assert client.post(
        "/api/region-sets/replace", json=_two_regions([0, 0, 3, 3], [10, 10, 13, 13])
    ).status_code == 200
    preview = _preview(client, _image(), region_ref="picked")
    assert preview["pixel_count"] == 32
    assert preview["bbox_pixels"] == 196
    assert preview["exact_mask"] is True
    assert preview["provenance"]["region_ids"] == ["r0", "r1"]


def test_a_single_region_inside_a_set_scopes_to_that_region(client) -> None:
    """`set/region` selects one region, not the set's union — the other
    half of §7, and the reference form a UI uses when a user clicks one
    row of the region table."""
    assert client.post(
        "/api/region-sets/replace", json=_two_regions([0, 0, 9, 9], [20, 20, 29, 29])
    ).status_code == 200
    whole = _preview(client, _image(), region_ref="picked")
    one = _preview(client, _image(), region_ref="picked/r0")
    assert whole["pixel_count"] == 200
    assert one["pixel_count"] == 100
    assert one["provenance"]["region_ids"] == ["r0"]


def test_a_malformed_roi_string_is_refused(client) -> None:
    """The roi is a frozen `"r1,c1,r2,c2"` string, parsed by the resolver.
    A caller sending a rect tuple or a short string gets a 422 rather
    than a 500 from inside the parser."""
    image_id = _image()
    for bad in ("not,a,rect", "1,2,3", "1,2,3,4,5", " "):
        r = client.post(
            "/api/regions/preview", json={"image_id": image_id, "roi": bad}
        )
        assert r.status_code == 422, bad

    # Only the EMPTY string means "no roi given". A whitespace one does
    # not: the resolver tests truthiness, not `.strip()`, so " " is a
    # malformed rect rather than an absent one — asserted because the two
    # look alike to a caller building the string by concatenation.
    assert client.post(
        "/api/regions/preview", json={"image_id": image_id, "roi": ""}
    ).json()["pixel_count"] == 40 * 60


def test_a_spectrum_is_refused_with_a_message_about_previewing(client) -> None:
    """The shared `_raster` helper hard-coded "to segment", so previewing
    a 1-D spectrum reported the failure of an operation the caller never
    invoked. Both callers are asserted here, because the fix was to give
    the helper the caller's purpose and a helper that ignored it would
    look identical from either side alone.
    """
    ds = DataStruct(
        data=np.arange(50.0), kind=DataKind.SPECTRUM, axes=(AxisCal(),), metadata={}
    )
    spec_id = store.add_parsed(ds, "spec.msa")

    preview = client.post("/api/regions/preview", json={"image_id": spec_id})
    assert preview.status_code == 400
    assert preview.json()["detail"] == "1D spectra have no raster to preview a region over"

    propose = client.post(
        "/api/regions/propose", json={"image_id": spec_id, "seed": [0.5, 0.5]}
    )
    assert propose.status_code == 400
    assert propose.json()["detail"] == "1D spectra have no raster to segment"


# ── cheap, as the name promises ──────────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "shape"),
    [
        (DataKind.IMAGE, (17, 23)),
        (DataKind.RGB_IMAGE, (17, 23, 3)),
        (DataKind.SPECTRUM_IMAGE, (17, 23, 8)),
    ],
)
def test_the_grid_matches_what_the_raster_would_have_said(
    client, kind: DataKind, shape: tuple[int, ...]
) -> None:
    """`_spatial_shape` replaces `raster_of` for the grid, so the two must
    agree for every raster-bearing kind — otherwise the preview would
    scope against a different grid than the analysis it previews. Odd,
    unequal dimensions so a transposition cannot pass."""
    axes = tuple(AxisCal() for _ in range(2 if kind is DataKind.RGB_IMAGE else len(shape)))
    data = np.zeros(shape, dtype=np.uint8 if kind is DataKind.RGB_IMAGE else np.float64)
    ds = DataStruct(data=data, kind=kind, axes=axes, metadata={})
    image_id = store.add_parsed(ds, f"{kind.value}.dm4")

    from fermiviewer.calc.raster import raster_of

    assert raster_of(ds).shape == (17, 23), "the grid the analyses use"
    assert _preview(client, image_id)["image_pixels"] == 17 * 23


def test_previewing_does_not_copy_the_image(client) -> None:
    """The claim the endpoint's name makes: cheap BEFORE expensive work.

    `raster_of` was called only for `.shape`, and it does real work for
    every kind first — a plain IMAGE is copied to float64, RGB is reduced
    to luminance, a SPECTRUM_IMAGE is summed over its whole cube. So a
    preview cost a full pass over the data it was supposed to precede,
    and "this route reads no pixel value" was false when I wrote it.

    A plain IMAGE is the case measured, deliberately. My first version of
    this test used a spectrum image and would have measured nothing: that
    path READS the cube but allocates only the small summed output, so
    its cost is time rather than memory. The float64 copy is where the
    cost is visible to `tracemalloc`.

    The bound sits between two measurements on this 4.2 MB float32 image:
    8.468 MB through `raster_of` (the copy, plus the original) against
    0.083 MB through `.shape`. 1 MB is ~12x the real peak, so a slower
    machine or a different numpy has room, and ~1/8 of the regression, so
    the regression cannot hide under it. The first call is made and
    discarded because one-time framework setup would otherwise be counted
    as the request's cost.
    """
    import tracemalloc

    data = np.zeros((1024, 1024), dtype=np.float32)
    ds = DataStruct(
        data=data, kind=DataKind.IMAGE, axes=(AxisCal(), AxisCal()), metadata={}
    )
    image_id = store.add_parsed(ds, "big.tif")
    assert data.nbytes == 4194304

    _preview(client, image_id, roi="1,1,10,10")  # warm the request path
    tracemalloc.start()
    try:
        assert _preview(client, image_id, roi="1,1,10,10")["pixel_count"] == 100
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 1_000_000, f"peak {peak} suggests the image was copied"


def test_both_of_section_nine_s_answers_are_reported(client) -> None:
    """ADR 0007 §9 gives two different answers for an irregular region,
    and the preview must carry both rather than pick one.

    A reducing analysis reads the SELECTION; a neighbourhood-based one
    reads the bounding-box CROP and clips its labels to the selection. So
    `pixel_count` is what may carry a result, `bbox_pixels` is what
    informs it, and `exact_mask` says whether they differ at all.

    Pinned as a relationship, not as constants: whenever the mask is
    exact the two must diverge, and whenever it is not they must agree.
    A response reporting one number for "what will be read" would fail
    the first half.
    """
    image_id = _image()
    _install(client)
    irregular = _preview(client, image_id, region_ref="picked")
    assert irregular["exact_mask"] is True
    assert irregular["pixel_count"] < irregular["bbox_pixels"], (
        "a hole means the analysis reads wider than it labels"
    )

    plain = _preview(client, image_id, roi="3,4,12,20")
    assert plain["exact_mask"] is False
    assert plain["pixel_count"] == plain["bbox_pixels"], (
        "a rectangle is its own context, so §9's two answers coincide"
    )
