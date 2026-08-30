"""4C-5 — a recipe's named region, and cross-consumer agreement.

Two things are asserted here, and the second is item 4's "Done when".

**Substitution is lossless.** A reference resolved by name and the same
reference substituted into an op's inline geometry must select the SAME
pixels. The oracle is `region_resolve.resolve_region` — the 4C-0 path
every route already uses — so this is a comparison between two
independent implementations, not a restatement of one.

**Consumers agree.** The same region reference run through the spectrum,
statistics, particle, grain and layer consumers must select the same
pixels in all of them. That is checked against a mask rasterized by
`calc.region_mask.rasterize`, so five agreeing consumers cannot all be
agreeing on the wrong thing.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

import fermiviewer.ops as ops
from fermiviewer.calc.region_mask import rasterize
from fermiviewer.calc.regions import Part, Region, Shape
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.regions_model import RegionSet
from fermiviewer.ops._region_param import region_from_params
from fermiviewer.recipe_regions import (
    RegionReferenceError,
    recipe_region_refs,
    region_param_json,
    substitute_region_refs,
)
from fermiviewer.region_resolve import resolve_region

pytestmark = pytest.mark.parser

GRID = (40, 40)


def _image(data: np.ndarray | None = None) -> DataStruct:
    if data is None:
        rng = np.random.default_rng(5)
        data = rng.normal(60.0, 9.0, GRID)
        data[10:30, 10:30] += 40.0
    return DataStruct(
        data=np.asarray(data, dtype=np.float64),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
        metadata={"source": "synthetic"},
    )


def _named(result: Any, name: str) -> dict[str, Any]:
    return next(o for o in result.value["outputs"] if o["name"] == name)["data"]


def _provenance(result: Any) -> dict[str, Any]:
    """The `region` provenance, whichever result shape the op uses.

    `image_stats` returns a FLAT value dict and the rest return an
    outputs list. That split predates 4C and is not this wave's to fix,
    so the test reads both rather than quietly dropping the one op whose
    shape is inconvenient.
    """
    if "outputs" in result.value:
        return _named(result, "region")
    return dict(result.value["region"])


def _region(*parts: Part, region_id: str = "r1") -> Region:
    return Region(id=region_id, parts=parts)


def _set(*regions: Region, set_id: str = "s1", image_id: str | None = None) -> RegionSet:
    return RegionSet(id=set_id, regions=regions, image_id=image_id)


def _pixels(mask: np.ndarray) -> set[tuple[int, int]]:
    return {(int(r), int(c)) for r, c in zip(*np.nonzero(mask), strict=True)}


def _named_pixels(sets: tuple[RegionSet, ...], ref: str) -> set[tuple[int, int]]:
    """The pixel set the 4C-0 resolver selects — the oracle."""
    resolved = resolve_region(GRID, region=ref, sets=sets)
    rows, cols = resolved.rect_slices()
    cropped = resolved.cropped_mask()
    return {(rows.start + r, cols.start + c) for r, c in zip(*np.nonzero(cropped), strict=True)}


def _substituted_pixels(sets: tuple[RegionSet, ...], ref: str) -> set[tuple[int, int]]:
    """The pixel set the SUBSTITUTED inline geometry selects."""
    steps = [{"op": "image_stats", "region_ref": ref}]
    (step,) = substitute_region_refs(steps, sets)
    scoped = region_from_params(step["params"], GRID)
    assert scoped is not None
    full = np.zeros(GRID, dtype=bool)
    r1, c1, r2, c2 = scoped.rect
    if scoped.mask is None:
        full[r1 - 1 : r2, c1 - 1 : c2] = True
    else:
        full = scoped.mask
    return _pixels(full)


# ── substitution is lossless ─────────────────────────────────────────

_ELLIPSE = Shape(kind="ellipse", bounds=(6.0, 6.0, 28.0, 30.0))
_RECT = Shape(kind="rect", bounds=(4.0, 4.0, 20.0, 20.0))
_POLY = Shape(
    kind="polygon",
    outline=np.array([[5.0, 5.0], [5.0, 25.0], [22.0, 25.0], [18.0, 8.0]]),
)
_HOLED = Shape(
    kind="rect",
    bounds=(4.0, 4.0, 30.0, 30.0),
    holes=(
        np.array([[8.0, 8.0], [8.0, 14.0], [14.0, 14.0], [14.0, 8.0]]),
        np.array([[20.0, 20.0], [20.0, 26.0], [26.0, 26.0], [26.0, 20.0]]),
    ),
)


@pytest.mark.parametrize(
    ("label", "shape"),
    [("rect", _RECT), ("ellipse", _ELLIPSE), ("polygon", _POLY), ("two holes", _HOLED)],
)
def test_substituting_a_named_region_selects_the_same_pixels(label: str, shape: Shape) -> None:
    sets = (_set(_region(Part(shape))),)
    assert _substituted_pixels(sets, "s1/r1") == _named_pixels(sets, "s1/r1"), label


def test_a_whole_set_reference_substitutes_as_a_union_not_a_flattening() -> None:
    """The reason `group` exists. Region B excludes pixels that region A
    includes; flattened into one parts list B's exclude eats A's, and the
    substituted geometry selects fewer pixels than the name does."""
    a = _region(Part(Shape(kind="rect", bounds=(4.0, 4.0, 20.0, 20.0))), region_id="a")
    b = _region(
        Part(Shape(kind="rect", bounds=(10.0, 10.0, 30.0, 30.0))),
        Part(Shape(kind="rect", bounds=(12.0, 12.0, 18.0, 18.0)), mode="exclude"),
        region_id="b",
    )
    sets = (_set(a, b),)
    by_name = _named_pixels(sets, "s1")
    assert _substituted_pixels(sets, "s1") == by_name
    # and the union really is bigger than the flattening would give, or
    # the assertion above would hold for the wrong reason
    flat = region_param_json((a, b))
    for item in flat:
        item["group"] = 0
    flattened = region_from_params({"region": flat}, GRID)
    assert flattened is not None
    assert flattened.mask is not None
    assert len(_pixels(flattened.mask)) < len(by_name)


def test_every_region_gets_its_own_group() -> None:
    sets = (_set(_region(Part(_RECT), region_id="a"), _region(Part(_ELLIPSE), region_id="b")),)
    (step,) = substitute_region_refs([{"op": "image_stats", "region_ref": "s1"}], sets)
    assert sorted({p["group"] for p in step["params"]["region"]}) == [0, 1]
    (one,) = substitute_region_refs([{"op": "image_stats", "region_ref": "s1/a"}], sets)
    assert {p["group"] for p in one["params"]["region"]} == {0}


def test_the_substituted_params_are_a_complete_reproduction_key() -> None:
    """ADR 0005: the recorded params ARE the replay key. After
    substitution nothing in the step refers to the project, so the same
    numbers come out with no region sets present at all."""
    sets = (_set(_region(Part(_ELLIPSE))),)
    (step,) = substitute_region_refs([{"op": "image_stats", "region_ref": "s1/r1"}], sets)
    assert "region_ref" not in step
    assert "s1" not in repr(step["params"])

    ds = _image()
    from_recipe = ops.run("image_stats", ds, step["params"])
    replayed = ops.run("image_stats", ds, dict(from_recipe.params))
    # replayed from the RECORDED params, not from the recipe source: that
    # is the round trip ADR 0005 promises, and it must not need the set
    assert replayed.value["mean"] == from_recipe.value["mean"]
    assert replayed.value["n_finite"] == from_recipe.value["n_finite"]
    # and the scope really bit — a whole-image run differs
    assert ops.run("image_stats", ds, {}).value["n_finite"] != from_recipe.value["n_finite"]


def test_substitution_does_not_mutate_the_recipe() -> None:
    """A batch reuses one recipe across many images. Substituting in
    place would leave image 2 running image 1's geometry — and with a
    bound set, image 2 would silently inherit a region it must have been
    refused."""
    sets = (_set(_region(Part(_ELLIPSE))),)
    steps = [{"op": "image_stats", "region_ref": "s1/r1"}]
    substitute_region_refs(steps, sets)
    substitute_region_refs(steps, sets)
    assert steps == [{"op": "image_stats", "region_ref": "s1/r1"}]


def test_a_step_may_not_name_a_region_and_inline_one() -> None:
    sets = (_set(_region(Part(_RECT))),)
    with pytest.raises(RegionReferenceError, match="not both"):
        substitute_region_refs(
            [
                {
                    "op": "image_stats",
                    "region_ref": "s1/r1",
                    "params": {"region": [{"kind": "rect", "bounds": [[0, 0, 5, 5]]}]},
                }
            ],
            sets,
        )


def test_a_set_drawn_on_another_image_is_refused_naming_the_image() -> None:
    sets = (_set(_region(Part(_RECT)), image_id="img-A"),)
    steps = [{"op": "image_stats", "region_ref": "s1/r1"}]
    assert substitute_region_refs(steps, sets, "img-A")[0]["params"]["region"]
    with pytest.raises(RegionReferenceError, match="img-B"):
        substitute_region_refs(steps, sets, "img-B")


def test_an_unbound_set_resolves_for_every_image() -> None:
    """The escape hatch that makes a batch-wide region possible: ADR 0006
    leaves `image_id` optional, and an unbound set is not claiming to
    belong to one specimen."""
    sets = (_set(_region(Part(_RECT))),)
    for image_id in ("img-A", "img-B", None):
        assert substitute_region_refs(
            [{"op": "image_stats", "region_ref": "s1/r1"}], sets, image_id
        )[0]["params"]["region"]


def test_steps_without_a_reference_pass_through_untouched() -> None:
    steps = [{"op": "gaussian", "params": {"sigma": 2.0}}]
    assert substitute_region_refs(steps, ()) == steps
    assert substitute_region_refs(steps, ())[0] is steps[0]


def test_recipe_region_refs_lists_each_name_once_in_order() -> None:
    steps = [
        {"op": "image_stats", "region_ref": "b"},
        {"op": "gaussian"},
        {"op": "image_stats", "region_ref": "a"},
        {"op": "image_stats", "region_ref": "b"},
        {"op": "image_stats", "region_ref": ""},
    ]
    assert recipe_region_refs(steps) == ["b", "a"]


def test_an_unknown_reference_raises_rather_than_widening() -> None:
    with pytest.raises(RegionReferenceError):
        substitute_region_refs([{"op": "image_stats", "region_ref": "nope"}], ())


def test_a_non_string_reference_is_refused() -> None:
    with pytest.raises(RegionReferenceError, match="must be a string"):
        substitute_region_refs([{"op": "image_stats", "region_ref": 7}], ())


# ── cross-consumer agreement (item 4's "Done when") ──────────────────


def _cube(grid: tuple[int, int] = GRID, n_channels: int = 6) -> DataStruct:
    rng = np.random.default_rng(7)
    data = rng.normal(20.0, 3.0, (*grid, n_channels))
    return DataStruct(
        data=data,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(
            AxisCal(0.5, 0.0, "nm"),
            AxisCal(0.5, 0.0, "nm"),
            AxisCal(1.0, 0.0, "eV"),
        ),
        metadata={"source": "synthetic"},
    )


CONSUMERS = [
    ("sum_spectrum", "spectrum"),
    ("image_stats", "image"),
    ("particles", "image"),
    ("grains", "image"),
    ("layers", "image"),
]


@pytest.mark.parametrize(("op_name", "subject"), CONSUMERS)
def test_every_consumer_reads_the_same_region_as_the_resolver(op_name: str, subject: str) -> None:
    """Item 4's "Done when": one region, one set of pixels, every
    consumer. Each op reports the rect it used and whether its selection
    was exact; both are compared with a mask rasterized independently by
    `calc.region_mask`, so agreement between the ops is not enough to
    pass — they have to agree with the geometry.
    """
    shape = Shape(kind="ellipse", bounds=(6.0, 6.0, 28.0, 30.0))
    sets = (_set(_region(Part(shape))),)
    (step,) = substitute_region_refs([{"op": op_name, "region_ref": "s1/r1"}], sets)

    expected = rasterize(_region(Part(shape)), GRID)
    rows = np.flatnonzero(expected.any(axis=1))
    cols = np.flatnonzero(expected.any(axis=0))
    expected_rect = [int(rows[0]) + 1, int(cols[0]) + 1, int(rows[-1]) + 1, int(cols[-1]) + 1]

    ds = _cube() if subject == "spectrum" else _image()
    params = dict(step["params"])
    if op_name == "layers":
        params["axis"] = "y"
    run = ops.run(op_name, ds, params)

    reported = _provenance(run)
    assert reported["rows"] == [expected_rect], op_name
    assert reported["exact_mask"] is True, op_name
    assert reported["position_convention"] == "1-based, inclusive, clamped", op_name


def test_a_rectangular_reference_is_reported_as_inexact_everywhere() -> None:
    """The other half of the invariant: `exact_mask` False means the rect
    IS the selection (ADR 0007 §3). If a consumer reported True for a
    plain rectangle it would be telling a caller to take a slow path for
    nothing — and the whole-image consumers would disagree with each
    other about a region that is not ambiguous at all."""
    sets = (_set(_region(Part(Shape(kind="rect", bounds=(4.0, 4.0, 20.0, 20.0))))),)
    (step,) = substitute_region_refs([{"op": "image_stats", "region_ref": "s1/r1"}], sets)
    for op_name, subject in CONSUMERS:
        params = dict(step["params"])
        if op_name == "layers":
            params["axis"] = "y"
        ds = _cube() if subject == "spectrum" else _image()
        reported = _provenance(ops.run(op_name, ds, params))
        assert reported["exact_mask"] is False, op_name
        assert reported["rows"] == [[5, 5, 21, 21]], op_name
