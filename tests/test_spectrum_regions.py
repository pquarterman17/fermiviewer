"""EDS/EELS spectrum integration over exact masks — roadmap 4C-1.

The first analysis migrated onto the canonical region contract:
`GET /image/{id}/spectrum` gains `region_ref`, a named region from the
ADR 0006 workspace, and sums its EXACT mask rather than its bounding box.

## What these tests are for

The roadmap asks each wave to "compare exact-mask results against the
legacy rectangular path", and that comparison has two halves that fail in
opposite directions:

* a RECTANGLE reached through the new path must reproduce the old answer
  exactly — otherwise the migration silently changes published numbers;
* a NON-RECTANGULAR region must NOT equal its bounding rectangle —
  otherwise the exact mask is decorative and the whole wave is a no-op
  that every "does it still work?" test would happily pass.

Expected counts come from summing the cube over an independently built
pixel set (`sum_over`), never from the resolver or from
`masked_sum_spectrum`, so a failure means the endpoint disagrees with
what the region means rather than that two spellings drifted apart.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.raster import masked_sum_spectrum, region_sum_spectrum
from fermiviewer.calc.regions import Part, Region, circle, rect
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.regions_model import RegionSet
from fermiviewer.project_session import project
from fermiviewer.server import create_app
from fermiviewer.session import store

H, W, C = 8, 8, 5


def a_cube() -> np.ndarray:
    """Distinct per-pixel spectra, so which pixels were summed is
    recoverable from the answer rather than masked by symmetry."""
    rng = np.random.default_rng(11)
    return rng.integers(1, 500, size=(H, W, C)).astype(np.uint16)


def sum_over(cube: np.ndarray, pixels: set[tuple[int, int]]) -> np.ndarray:
    """The oracle: sum the cube over an explicit 0-based pixel set, one
    pixel at a time. Deliberately a loop — no masks, no slicing, nothing
    that shares an implementation with the code under test."""
    total = np.zeros(cube.shape[2], dtype=np.float64)
    for r, c in sorted(pixels):
        total += cube[r, c, :].astype(np.float64)
    return total


def rect_pixels(r0: int, c0: int, r1: int, c1: int) -> set[tuple[int, int]]:
    """0-based INCLUSIVE rect, straight from the definition."""
    return {
        (r, c)
        for r in range(H)
        for c in range(W)
        if r0 <= r <= r1 and c0 <= c <= c1
    }


@pytest.fixture()
def client():
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


def load_cube(client, cube: np.ndarray, img_id: str = "img1") -> str:
    store.restore(
        img_id,
        DataStruct(
            data=cube,
            kind=DataKind.SPECTRUM_IMAGE,
            # energy axis is ALWAYS last for spectral kinds
            axes=(
                AxisCal(1.0, units="nm"),
                AxisCal(1.0, units="nm"),
                AxisCal(0.01, units="keV"),
            ),
        ),
        "si.dm4",
    )
    return img_id


def put_regions(*regions: Region, set_id: str = "s1", image_id="img1") -> None:
    project.replace_regions(
        (RegionSet(id=set_id, regions=regions, image_id=image_id),), ()
    )


def spectrum(client, img_id: str, **query) -> dict:
    resp = client.get(f"/api/image/{img_id}/spectrum", params=query)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── parity with the legacy rectangular path ──────────────────────────


def test_a_rect_region_reproduces_the_legacy_corner_answer(client) -> None:
    """The migration's core promise: routing a RECTANGLE through the new
    named-region path must not change the number the endpoint reports."""
    cube = a_cube()
    load_cube(client, cube)
    put_regions(Region(id="r1", parts=(Part(rect(2, 3, 5, 6)),)))

    legacy = spectrum(client, "img1", row0=3, col0=4, row1=6, col1=7)
    named = spectrum(client, "img1", region_ref="s1/r1")

    assert named["counts"] == legacy["counts"]
    assert named["region"] == legacy["region"] == [3, 4, 6, 7]
    assert named["counts"] == sum_over(cube, rect_pixels(2, 3, 5, 6)).tolist()


def test_a_rect_region_carries_no_exact_mask_flag(client) -> None:
    """`exact_mask` false says the reported rect IS the selection, which
    is what lets a rect-only client keep trusting `region` (ADR 0007 §3)."""
    load_cube(client, a_cube())
    put_regions(Region(id="r1", parts=(Part(rect(2, 3, 5, 6)),)))
    assert spectrum(client, "img1", region_ref="s1/r1")["exact_mask"] is False
    assert spectrum(client, "img1", row0=3, col0=4, row1=6, col1=7)[
        "exact_mask"
    ] is False


def test_the_whole_cube_answer_is_unchanged(client) -> None:
    cube = a_cube()
    load_cube(client, cube)
    got = spectrum(client, "img1")
    assert got["region"] is None
    assert got["exact_mask"] is False
    assert got["counts"] == cube.sum(axis=(0, 1), dtype=np.float64).tolist()


# ── the exact mask actually changes the answer ───────────────────────


def test_a_round_region_sums_less_than_its_bounding_rectangle(client) -> None:
    """The reason 4C-1 exists. If this passed by equality the mask would be
    decorative and every other test here would still be green."""
    cube = a_cube()
    load_cube(client, cube)
    put_regions(Region(id="disc", parts=(Part(circle(3.5, 3.5, 3.0)),)))

    exact = spectrum(client, "img1", region_ref="s1/disc")
    assert exact["exact_mask"] is True
    r0, c0, r1, c1 = exact["region"]
    boxed = spectrum(client, "img1", row0=r0, col0=c0, row1=r1, col1=c1)

    assert exact["counts"] != boxed["counts"], "the mask must exclude corners"
    assert all(e < b for e, b in zip(exact["counts"], boxed["counts"], strict=True))


def test_the_summed_pixels_are_exactly_the_regions_pixels(client) -> None:
    """Not just "smaller than the box" — the RIGHT pixels. The oracle is
    the circle's own definition from `calc/regions.py`: the pixel centres
    within an INCLUSIVE `radius` of the centre, `dist <= r`. Radius 3 on
    this grid keeps the bounding box interior (rows/cols 2..7, 1-based),
    so the test also pins that the box is not silently the whole image."""
    cube = a_cube()
    load_cube(client, cube)
    put_regions(Region(id="disc", parts=(Part(circle(3.5, 3.5, 3.0)),)))

    inside = {
        (r, c)
        for r in range(H)
        for c in range(W)
        if (r - 3.5) ** 2 + (c - 3.5) ** 2 <= 3.0**2
    }
    got = spectrum(client, "img1", region_ref="s1/disc")
    assert got["counts"] == sum_over(cube, inside).tolist()
    assert got["region"] == [2, 2, 7, 7], "bbox of the disc, 1-based inclusive"
    assert len(inside) < 6 * 6, "and it does not fill that box"


def test_an_excluded_hole_is_absent_from_the_sum(client) -> None:
    """An `exclude` part must remove counts, not merely shrink the box."""
    cube = a_cube()
    load_cube(client, cube)
    put_regions(
        Region(
            id="ring",
            parts=(Part(rect(1, 1, 6, 6)), Part(rect(3, 3, 4, 4), mode="exclude")),
        )
    )
    expected = rect_pixels(1, 1, 6, 6) - rect_pixels(3, 3, 4, 4)
    got = spectrum(client, "img1", region_ref="s1/ring")
    assert got["exact_mask"] is True
    assert got["counts"] == sum_over(cube, expected).tolist()


def test_a_whole_set_reference_sums_every_region_once(client) -> None:
    """Disjoint blobs are one selection — and overlapping ones must not be
    double-counted, which a naive sum-per-region would do."""
    cube = a_cube()
    load_cube(client, cube)
    put_regions(
        Region(id="a", parts=(Part(rect(0, 0, 3, 3)),)),
        Region(id="b", parts=(Part(rect(2, 2, 5, 5)),)),
    )
    union = rect_pixels(0, 0, 3, 3) | rect_pixels(2, 2, 5, 5)
    got = spectrum(client, "img1", region_ref="s1")
    assert got["counts"] == sum_over(cube, union).tolist()


# ── refusals ─────────────────────────────────────────────────────────


def test_giving_both_scopes_is_refused(client) -> None:
    load_cube(client, a_cube())
    put_regions(Region(id="r1", parts=(Part(rect(1, 1, 4, 4)),)))
    resp = client.get(
        "/api/image/img1/spectrum",
        params={"row0": 1, "col0": 1, "row1": 4, "col1": 4, "region_ref": "s1/r1"},
    )
    assert resp.status_code == 422
    assert "not both" in resp.text


@pytest.mark.parametrize(
    "reference", ["nope/r1", "s1/nope", "s1/", ""], ids=["set", "region", "half", "none"]
)
def test_an_unresolvable_reference_never_widens_to_the_whole_cube(
    client, reference
) -> None:
    """The failure that would be worst here: silently summing the entire
    cube when the caller scoped it to a region. An empty `region_ref` IS
    the whole cube (it means "unscoped"), so it is the control."""
    cube = a_cube()
    load_cube(client, cube)
    put_regions(Region(id="r1", parts=(Part(rect(1, 1, 4, 4)),)))
    resp = client.get("/api/image/img1/spectrum", params={"region_ref": reference})
    whole = cube.sum(axis=(0, 1), dtype=np.float64).tolist()
    if reference == "":
        assert resp.status_code == 200 and resp.json()["counts"] == whole
    else:
        assert resp.status_code == 422, resp.text
        assert "counts" not in resp.text


def test_a_region_drawn_on_another_image_is_refused(client) -> None:
    """Numbers from the wrong specimen are the scientific failure the
    image binding exists to prevent."""
    load_cube(client, a_cube(), "img1")
    load_cube(client, a_cube(), "img2")
    put_regions(Region(id="r1", parts=(Part(rect(1, 1, 4, 4)),)), image_id="img1")
    resp = client.get("/api/image/img2/spectrum", params={"region_ref": "s1/r1"})
    assert resp.status_code == 422
    assert "drawn on image" in resp.text


def test_a_region_reference_on_a_1d_spectrum_is_ignored_as_before(client) -> None:
    """Pre-4C behaviour, deliberately unchanged: a scope on a 1D spectrum
    is ignored rather than refused, because clients pass one
    unconditionally and 4C-1 is not the place to break them."""
    spec = np.arange(C, dtype=np.uint16)
    store.restore(
        "spec1",
        DataStruct(
            data=spec,
            kind=DataKind.SPECTRUM,
            axes=(AxisCal(0.01, units="keV"),),
        ),
        "line.msa",
    )
    got = spectrum(client, "spec1", region_ref="s1/r1")
    assert got["region"] is None
    assert got["exact_mask"] is False


# ── the calc function both paths share ───────────────────────────────


def test_masked_sum_spectrum_without_a_mask_is_the_legacy_expression() -> None:
    """`region_sum_spectrum` now delegates here, so this pins that the
    delegation did not change the rectangle answer."""
    cube = a_cube()
    for r in [(1, 1, H, W), (2, 3, 5, 6), (4, 4, 4, 4), (1, 1, 1, W)]:
        legacy, rect_used = region_sum_spectrum(cube, *r)
        assert np.array_equal(masked_sum_spectrum(cube, rect_used), legacy)
        assert np.array_equal(
            legacy, sum_over(cube, rect_pixels(r[0] - 1, r[1] - 1, r[2] - 1, r[3] - 1))
        )


def test_masked_sum_spectrum_refuses_a_mask_of_the_wrong_shape() -> None:
    """A shape mismatch means the caller paired a mask with someone else's
    rect; summing whatever broadcast would produce is not a defensible
    number."""
    cube = a_cube()
    with pytest.raises(ValueError, match="does not match"):
        masked_sum_spectrum(cube, (1, 1, 4, 4), np.ones((3, 3), dtype=bool))


def test_an_all_true_mask_equals_the_no_mask_answer() -> None:
    """The `mask is None` fast path must be an optimization, not a
    different calculation."""
    cube = a_cube()
    full = np.ones((H, W), dtype=bool)
    assert np.array_equal(
        masked_sum_spectrum(cube, (2, 3, 5, 6), full),
        masked_sum_spectrum(cube, (2, 3, 5, 6)),
    )
