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
from fermiviewer.ops.base import OpParam, ParamError, RowSpec
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
            "holes": [[[2, 2], [2, 3], [3, 2]]],
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


def test_a_whole_set_union_survives_the_inline_form(client) -> None:
    """P1. A bare `set_id` reference rasterizes each Region INDEPENDENTLY and
    unions the finished masks, so one region's `exclude` must not subtract
    from another's pixels. Flattening every part into one ordered list makes
    it: region A (full image) + region B (include then exclude) gives 60 px
    flattened where the named union gives 64. `group` is what keeps the
    boundary, so a caller substituting a whole-set reference can reproduce
    it rather than silently changing the pixels."""
    cube = a_cube()
    store.restore("img1", a_cube_ds(cube), "si.dm4")
    whole = Region(id="a", parts=(Part(rect(0, 0, H - 1, W - 1)),))
    holed = Region(
        id="b",
        parts=(Part(rect(0, 0, 3, 3)), Part(rect(1, 1, 2, 2), mode="exclude")),
    )
    project.replace_regions(
        (RegionSet(id="s1", regions=(whole, holed), image_id="img1"),), ()
    )
    named = client.get(
        "/api/image/img1/spectrum", params={"region_ref": "s1"}
    ).json()

    grouped = run("sum_spectrum", a_cube_ds(cube), {"region": geo(
        {"kind": "rect", "bounds": [[0, 0, H - 1, W - 1]], "group": 0},
        {"kind": "rect", "bounds": [[0, 0, 3, 3]], "group": 1},
        {"kind": "rect", "bounds": [[1, 1, 2, 2]], "mode": "exclude", "group": 1},
    )})
    counts = next(
        o for o in grouped.value["outputs"] if o["name"] == "counts"
    )["data"]["y"]
    assert counts == named["counts"]
    # and it is the whole image, which the flattened spelling is NOT
    assert counts == sum_over(cube, rect_pixels(0, 0, H - 1, W - 1))

    flattened = run("sum_spectrum", a_cube_ds(cube), {"region": geo(
        {"kind": "rect", "bounds": [[0, 0, H - 1, W - 1]]},
        {"kind": "rect", "bounds": [[0, 0, 3, 3]]},
        {"kind": "rect", "bounds": [[1, 1, 2, 2]], "mode": "exclude"},
    )})
    flat_counts = next(
        o for o in flattened.value["outputs"] if o["name"] == "counts"
    )["data"]["y"]
    assert flat_counts != counts, "one group really does subtract across"


def test_parts_in_one_group_still_apply_in_order() -> None:
    """The `group` field adds a union boundary WITHOUT weakening ordering
    inside a region — both rules have to hold at once."""
    ring = region_from_params({"region": geo(
        {"kind": "rect", "bounds": [[1, 1, 6, 6]], "group": 2},
        {"kind": "rect", "bounds": [[3, 3, 4, 4]], "mode": "exclude", "group": 2},
    )}, (H, W))
    assert ring is not None and int(ring.mask.sum()) == 6 * 6 - 2 * 2


def test_a_region_with_two_holes_is_expressible() -> None:
    """P2. `Shape.holes` is a SEQUENCE of rings. A single-ring param could
    not write down a perfectly valid two-hole region at all, which made the
    "canonical geometry" claim false."""
    outline = [(0, 0), (0, 7), (7, 0)]
    rings = [[(1, 1), (1, 2), (2, 1)], [(4, 1), (4, 2), (5, 1)]]
    scoped = region_from_params({"region": geo({
        "kind": "polygon",
        "outline": [list(p) for p in outline],
        "holes": [[list(p) for p in ring] for ring in rings],
    })}, (H, W))
    direct = rasterize(
        Region(id="x", parts=(Part(polygon(outline, holes=rings)),)), (H, W)
    )
    assert scoped is not None
    assert np.array_equal(scoped.mask, direct)


def test_two_holes_on_a_bounds_shape_too() -> None:
    """`holes` is supported for every kind, not just polygons."""
    rings = [[(1, 1), (1, 2), (2, 1)], [(5, 5), (5, 6), (6, 5)]]
    scoped = region_from_params({"region": geo({
        "kind": "rect", "bounds": [[0, 0, 7, 7]],
        "holes": [[list(p) for p in ring] for ring in rings],
    })}, (H, W))
    direct = rasterize(
        Region(id="x", parts=(Part(rect(0, 0, 7, 7, holes=rings)),)), (H, W)
    )
    assert scoped is not None
    assert np.array_equal(scoped.mask, direct)


def test_a_completed_run_cannot_mutate_the_schema_default() -> None:
    """P3, guarded at the level it was fixed: `_resolve_fields` used to hand
    out `spec.default` itself, so `OpResult.params` — public and mutable —
    aliased the schema. Appending to one run's params made the NEXT run with
    that param omitted take the geometry path with someone else's region."""
    ds = a_cube_ds(a_cube())
    first = run("sum_spectrum", ds, {})
    assert first.params["region"] is not REGION_PARAM.default
    first.params["region"].append({"kind": "rect", "bounds": [[0, 0, 1, 1]]})
    assert REGION_PARAM.default == [], "the schema must be untouched"

    second = run("sum_spectrum", ds, {})
    assert second.params["region"] == []
    assert not [o for o in second.value["outputs"] if o["name"] == "region"], (
        "a run with no region must stay unscoped"
    )


def test_nested_record_defaults_are_isolated_too() -> None:
    """The copy has to be deep: a record's row-list fields are mutable
    objects inside the default as well."""
    coerced = geo({"kind": "rect", "bounds": [[0, 0, 3, 3]]})
    assert coerced[0]["holes"] == [] and coerced[0]["outline"] == []
    coerced[0]["holes"].append([[1, 1], [1, 2], [2, 1]])
    fresh = geo({"kind": "rect", "bounds": [[0, 0, 3, 3]]})
    assert fresh[0]["holes"] == [], "a record's own list defaults must not alias"


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


@pytest.mark.parametrize(
    "holes, why",
    [
        ([[[1, 1, 1], [1, 2, 2]]], r"holes\[0\]\[0\].*expected 2 values"),
        ([[1, 1], [1, 2]], r"holes\[0\]\[0\].*expected a list, got int"),
        ("nope", r"holes.*expected a list, got str"),
        ([[[1, 1], [1, "x"]]], r"holes\[0\]\[1\]\.1.*cannot coerce 'x' to float"),
    ],
    ids=["3-wide-row", "bare-row-not-a-ring", "a-string", "non-numeric"],
)
def test_malformed_hole_rings_are_rejected(holes, why) -> None:
    """The rings shape has to VALIDATE, not just pass nested lists through.
    Without this, dropping the rings branch entirely still lets the data
    reach `np.asarray` and appear to work — which is exactly what a mutant
    revealed. The expected messages are asserted with their full index path
    (`holes[0][1].1`), because naming which ring, which row and which
    coordinate is the whole benefit of validating rather than passing
    through."""
    with pytest.raises(ParamError, match=why):
        REGION_PARAM.coerce("region", [
            {"kind": "rect", "bounds": [[0, 0, 3, 3]], "holes": holes}
        ])


def test_a_nested_default_is_deep_copied_not_shared() -> None:
    """The central `_resolve_fields` fix has to copy DEEPLY. A shallow copy
    duplicates the outer list while every caller keeps sharing the objects
    inside it, so mutating one run's nested row still edits the schema. No
    registered op has a non-empty nested default today, so this exercises
    the contract directly rather than through one."""
    from fermiviewer.ops.base import OpSpec

    nested_default = [[1.0, 2.0]]
    spec = OpSpec(
        name="_probe_deepcopy",
        category="analysis",
        summary="test-only probe",
        params={"pts": OpParam(ptype=list, default=nested_default,
                               row=RowSpec(width=2))},
        fn=lambda ds, params: None,
    )
    first = spec.resolve_params({})
    first["pts"][0].append(99.0)          # mutate a row INSIDE the default
    assert nested_default == [[1.0, 2.0]], "the schema's nested row must survive"
    assert spec.resolve_params({})["pts"] == [[1.0, 2.0]]


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
