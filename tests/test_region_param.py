"""A region as an op parameter — the 4C-5 prerequisite.

An op cannot resolve a region by name: `ops/registry.py` states that the
pure layer never looks an id up, because the caller owns the session
store. So `REGION_PARAM` carries the canonical GEOMETRY inline, validated
by the same `OpParam` machinery as every other parameter.

## Why this is the whole mechanism and not a stopgap

Naming is a caller concern. A recipe runner owns the session, so it can
resolve a symbolic reference and substitute the resolved geometry into
this param before dispatch — the op still never sees an id, `run()` never
changes, and the recorded params still carry the resolved values ADR 0005
requires as the reproduction key. `test_geometry_params_are_a_complete_
reproduction_key` pins the property that makes that work.

## Where the expected answers come from

The same independent oracle as the earlier waves: an explicitly built
pixel set, summed one pixel at a time. And the sharpest test here compares
the OP against the ROUTE on the same geometry — two independently written
consumers of the contract, which is exactly the cross-consumer agreement
item 4's "Done when" asks for.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.region_mask import mask_and_rect, rasterize
from fermiviewer.calc.regions import Part, Region, circle, polygon, rect
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.regions_model import RegionSet
from fermiviewer.ops._region_param import REGION_PARAM, region_from_params
from fermiviewer.ops.base import ParamError
from fermiviewer.ops.registry import run
from fermiviewer.project_session import project
from fermiviewer.server import create_app
from fermiviewer.session import store

H, W, C = 8, 8, 5


def a_cube() -> np.ndarray:
    rng = np.random.default_rng(11)
    return rng.integers(1, 500, size=(H, W, C)).astype(np.uint16)


def sum_over(cube: np.ndarray, pixels: set[tuple[int, int]]) -> list[float]:
    """The oracle: one pixel at a time, no masks, no slicing."""
    total = np.zeros(cube.shape[2], dtype=np.float64)
    for r, c in sorted(pixels):
        total += cube[r, c, :].astype(np.float64)
    return total.tolist()


def rect_pixels(r0: int, c0: int, r1: int, c1: int) -> set:
    return {
        (r, c)
        for r in range(H)
        for c in range(W)
        if r0 <= r <= r1 and c0 <= c <= c1
    }


def geo(*parts: dict) -> list[dict]:
    """Coerce geometry the way `run()` would, so tests exercise the real
    validation path rather than hand-built dicts."""
    return REGION_PARAM.coerce("region", list(parts))


def a_cube_ds(cube: np.ndarray) -> DataStruct:
    return DataStruct(
        data=cube,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(
            AxisCal(1.0, units="nm"),
            AxisCal(1.0, units="nm"),
            AxisCal(0.01, units="keV"),
        ),
    )


# ── the geometry becomes the right pixels ────────────────────────────


def test_a_rect_part_selects_its_pixels_and_fills_its_box() -> None:
    scoped = region_from_params({"region": geo({"kind": "rect", "bounds": [[2, 3, 5, 6]]})}, (H, W))
    assert scoped is not None
    assert scoped.rect == (3, 4, 6, 7), "0-based bounds -> 1-based rect"
    assert scoped.mask is None, "a plain rect fills its box (ADR 0007 §3)"


def test_parts_apply_in_order_so_an_include_after_an_exclude_restores() -> None:
    """`Region`'s ordering rule, reachable from JSON. If the param sorted
    or de-duplicated parts this would silently give a different region."""
    ring = region_from_params(
        {"region": geo(
            {"kind": "rect", "bounds": [[1, 1, 6, 6]]},
            {"kind": "rect", "bounds": [[3, 3, 4, 4]], "mode": "exclude"},
        )},
        (H, W),
    )
    restored = region_from_params(
        {"region": geo(
            {"kind": "rect", "bounds": [[1, 1, 6, 6]]},
            {"kind": "rect", "bounds": [[3, 3, 4, 4]], "mode": "exclude"},
            {"kind": "rect", "bounds": [[3, 3, 4, 4]]},
        )},
        (H, W),
    )
    assert ring is not None and restored is not None
    assert int(ring.mask.sum()) == 6 * 6 - 2 * 2
    assert restored.mask is None, "the re-include refills the box"


def test_an_unscoped_param_is_none_not_an_empty_region() -> None:
    """Empty means "whole image", so every adopting op stays backward
    compatible without the op writing its own default."""
    assert region_from_params({}, (H, W)) is None
    assert region_from_params({"region": []}, (H, W)) is None


def test_a_polygon_and_a_hole_survive_the_json_round_trip() -> None:
    scoped = region_from_params(
        {"region": geo({
            "kind": "polygon",
            "outline": [[1, 1], [1, 6], [6, 1]],
            "holes": [[2, 2], [2, 3], [3, 2]],
        })},
        (H, W),
    )
    assert scoped is not None and scoped.mask is not None
    direct = rasterize(
        Region(id="x", parts=(Part(polygon(
            [(1, 1), (1, 6), (6, 1)], holes=[[(2, 2), (2, 3), (3, 2)]]
        )),)),
        (H, W),
    )
    assert np.array_equal(scoped.mask, direct)


# ── the op agrees with the route: cross-consumer parity ──────────────


@pytest.fixture()
def client():
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


def test_the_op_and_the_route_agree_on_the_same_region(client) -> None:
    """The point of the whole contract. `sum_spectrum` reaches the region
    as inline geometry; `GET /image/{id}/spectrum` reaches it by name
    through the session. Two independently written consumers, one answer."""
    cube = a_cube()
    store.restore("img1", a_cube_ds(cube), "si.dm4")
    region = Region(id="disc", parts=(Part(circle(3.5, 3.5, 3.0)),))
    project.replace_regions(
        (RegionSet(id="s1", regions=(region,), image_id="img1"),), ()
    )

    named = client.get(
        "/api/image/img1/spectrum", params={"region_ref": "s1/disc"}
    ).json()

    shape = rasterize(region, (H, W))
    parts = [{"kind": "circle", "bounds": [list(map(float, circle(3.5, 3.5, 3.0).bounds))]}]
    result = run("sum_spectrum", a_cube_ds(cube), {"region": geo(*parts)})
    curve = next(o for o in result.value["outputs"] if o["name"] == "counts")
    table = next(o for o in result.value["outputs"] if o["name"] == "region")

    assert curve["data"]["y"] == named["counts"]
    assert table["data"]["rows"][0] == named["region"]
    assert table["data"]["exact_mask"] == named["exact_mask"] is True
    # and both agree with the oracle, so they are not merely equal
    inside = {
        (r, c) for r in range(H) for c in range(W)
        if (r - 3.5) ** 2 + (c - 3.5) ** 2 <= 9.0
    }
    assert curve["data"]["y"] == sum_over(cube, inside)
    assert int(shape.sum()) == len(inside)


def test_the_op_geometry_path_matches_its_own_corner_path(client) -> None:
    """A rectangle expressed as geometry must reproduce the legacy
    corner-param answer exactly — the parity every wave asserts."""
    cube = a_cube()
    ds = a_cube_ds(cube)
    corners = run("sum_spectrum", ds, {
        "region_row0": 3.0, "region_col0": 4.0,
        "region_row1": 6.0, "region_col1": 7.0,
    })
    inline = run("sum_spectrum", ds, {
        "region": geo({"kind": "rect", "bounds": [[2, 3, 5, 6]]})
    })
    a = next(o for o in corners.value["outputs"] if o["name"] == "counts")
    b = next(o for o in inline.value["outputs"] if o["name"] == "counts")
    assert a["data"]["y"] == b["data"]["y"]
    assert a["data"]["y"] == sum_over(cube, rect_pixels(2, 3, 5, 6))


def test_an_irregular_region_differs_from_its_bounding_rectangle() -> None:
    """Otherwise the geometry param would be decorative."""
    cube = a_cube()
    ds = a_cube_ds(cube)
    exact = run("sum_spectrum", ds, {
        "region": geo({"kind": "circle", "bounds": [[0.5, 0.5, 6.5, 6.5]]})
    })
    table = next(o for o in exact.value["outputs"] if o["name"] == "region")
    r = table["data"]["rows"][0]
    boxed = run("sum_spectrum", ds, {
        "region_row0": float(r[0]), "region_col0": float(r[1]),
        "region_row1": float(r[2]), "region_col1": float(r[3]),
    })
    assert table["data"]["exact_mask"] is True
    a = next(o for o in exact.value["outputs"] if o["name"] == "counts")["data"]["y"]
    b = next(o for o in boxed.value["outputs"] if o["name"] == "counts")["data"]["y"]
    assert a != b and all(x < y for x, y in zip(a, b, strict=True))


# ── reproducibility: the property the whole design rests on ──────────


def test_geometry_params_are_a_complete_reproduction_key() -> None:
    """No session, no project, no ids — the same params give the same
    numbers. This is why a named region can be resolved by the caller and
    substituted here: the recorded params stay self-contained."""
    cube = a_cube()
    params = {"region": geo({"kind": "polygon", "outline": [[1, 1], [1, 6], [6, 1]]})}
    first = run("sum_spectrum", a_cube_ds(cube), params)
    project.clear()
    store.clear()
    second = run("sum_spectrum", a_cube_ds(cube), params)
    def counts_of(result):
        return next(
            o for o in result.value["outputs"] if o["name"] == "counts"
        )["data"]["y"]

    assert counts_of(first) == counts_of(second)
    assert first.params["region"] == params["region"], "params echo resolved values"


def test_no_op_catalogue_reaches_into_the_session() -> None:
    """The rule this mechanism exists to respect, guarded here because
    tests/test_repo_integrity.py's pure-layer check would NOT catch it:
    FORBIDDEN_IN_PURE names the server stack, not session coupling."""
    from pathlib import Path

    ops_dir = Path(__file__).resolve().parents[1] / "src" / "fermiviewer" / "ops"
    forbidden = ("project_session", "region_resolve", "fermiviewer.session")
    offenders = [
        f"{path.name}: {line.strip()}"
        for path in ops_dir.rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(("import ", "from "))
        for bad in forbidden
        if bad in line
    ]
    assert not offenders, (
        "ops/ must not resolve ids — the caller owns the session store "
        "(ops/registry.py):\n  " + "\n  ".join(offenders)
    )


# ── refusals ─────────────────────────────────────────────────────────


def test_giving_both_corners_and_geometry_is_refused() -> None:
    with pytest.raises(ValueError, match="not both"):
        run("sum_spectrum", a_cube_ds(a_cube()), {
            "region_row0": 1.0, "region_col0": 1.0,
            "region_row1": 4.0, "region_col1": 4.0,
            "region": geo({"kind": "rect", "bounds": [[0, 0, 3, 3]]}),
        })


def test_geometry_selecting_nothing_is_refused_not_widened() -> None:
    """The failure that would be worst: silently summing the whole cube
    when the caller scoped it."""
    with pytest.raises(ValueError, match="selects no pixels"):
        region_from_params(
            {"region": geo({"kind": "rect", "bounds": [[90, 90, 95, 95]]})}, (H, W)
        )


@pytest.mark.parametrize(
    "part, why",
    [
        ({"kind": "polygon", "bounds": [[1, 1, 4, 4]]}, "needs 'outline'"),
        ({"kind": "rect", "outline": [[1, 1], [2, 2]]}, "needs 'bounds'"),
        ({"kind": "rect", "bounds": [[1, 1, 4, 4], [2, 2, 3, 3]]}, "exactly one"),
        # BOTH given: whichever the kind ignores would be silently dropped,
        # so the caller's other field has to be an error rather than noise.
        (
            {"kind": "polygon", "outline": [[1, 1], [1, 4], [4, 1]],
             "bounds": [[1, 1, 4, 4]]},
            "takes 'outline', not 'bounds'",
        ),
        (
            {"kind": "rect", "bounds": [[1, 1, 4, 4]],
             "outline": [[1, 1], [1, 4], [4, 1]]},
            "takes 'bounds', not 'outline'",
        ),
    ],
    ids=[
        "polygon-with-bounds", "rect-with-outline", "rect-with-two-rows",
        "polygon-with-both", "rect-with-both",
    ],
)
def test_bounds_and_outline_are_xor_by_kind(part, why) -> None:
    """`Shape.__post_init__` would catch the invariant, but its message is
    generic; the caller wrote JSON and needs to know which field to add."""
    with pytest.raises(ValueError, match=why):
        region_from_params({"region": geo(part)}, (H, W))


@pytest.mark.parametrize(
    "part, why",
    [
        ({"kind": "blob", "bounds": [[1, 1, 4, 4]]}, "not in"),
        ({"kind": "rect", "bounds": [[1, 1, 4]]}, "expected 4 values"),
        ({"kind": "rect", "bounds": [[1, 1, 4, 4]], "extra": 1}, "unknown param"),
        ({"kind": "rect", "bounds": [[1, 1, 4, 4]], "mode": "maybe"}, "not in"),
    ],
    ids=["kind", "row-width", "unknown-field", "mode"],
)
def test_malformed_geometry_is_rejected_by_the_param_machinery(part, why) -> None:
    """Validation is the ordinary `OpParam` path, so errors name the exact
    field — no bespoke schema for regions."""
    with pytest.raises(ParamError, match=why):
        REGION_PARAM.coerce("region", [part])


def test_a_region_on_a_1d_spectrum_is_refused() -> None:
    spec = DataStruct(
        data=np.arange(C, dtype=np.uint16),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(0.01, units="keV"),),
    )
    with pytest.raises(ValueError, match="spectrum-image cube"):
        run("sum_spectrum", spec, {
            "region": geo({"kind": "rect", "bounds": [[0, 0, 3, 3]]})
        })


def test_the_op_still_works_with_no_region_at_all() -> None:
    cube = a_cube()
    result = run("sum_spectrum", a_cube_ds(cube), {})
    curve = next(o for o in result.value["outputs"] if o["name"] == "counts")
    assert curve["data"]["y"] == cube.sum(axis=(0, 1), dtype=np.float64).tolist()
    assert not [o for o in result.value["outputs"] if o["name"] == "region"]


# ── the shared invariant ─────────────────────────────────────────────


def test_mask_and_rect_is_the_one_definition_of_the_none_invariant() -> None:
    """Both the named path and the geometry param go through it, so the
    rule cannot come to mean two things."""
    filled = rasterize(Region(id="r", parts=(Part(rect(1, 1, 4, 4)),)), (H, W))
    rect_, mask, count = mask_and_rect(filled)
    assert rect_ == (2, 2, 5, 5) and mask is None and count == 16

    disc = rasterize(Region(id="d", parts=(Part(circle(3.5, 3.5, 3.0)),)), (H, W))
    _, mask2, count2 = mask_and_rect(disc)
    assert mask2 is not None and count2 == int(disc.sum())

    with pytest.raises(ValueError, match="no pixels"):
        mask_and_rect(np.zeros((H, W), dtype=bool))
