"""The multi-image tiling ops registered against the re-opened contract:
``stitch``, ``montage``, ``montage_compare`` (ADR 0005 §8 auxiliary inputs,
§9 record params).

Every numeric assertion here is a PARITY assertion: the op is run through
``ops.run`` and its numbers are compared against calling the same ``calc/``
function the route calls, with the same inputs. That is the proof §1 asks
for — one op, one route, one calc function — since a reimplementation would
have to reproduce these arrays by accident to pass.

The rest pin the three places where the op is deliberately NOT a transcript
of its route: the equal-shape precondition stitch reproduces route-side,
the labels that ride ``metadata['source']`` because a pure op cannot read
the session store, and ``param_value``'s ``ANY_SCALAR`` ptype, which is what
keeps a numeric-looking STRING out of the numeric ordering.
"""

from __future__ import annotations

import numpy as np
import pytest

import fermiviewer.ops as ops
from fermiviewer.calc.montage import montage as calc_montage
from fermiviewer.calc.montage_physical import (
    montage_physical_scale,
    order_by_param_value,
)
from fermiviewer.calc.stitch import stitch_images
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops.base import InputError, ParamError

pytestmark = pytest.mark.parser


def _image(
    h: int = 24,
    w: int = 32,
    seed: int = 0,
    source: str = "",
    scale: float = 0.5,
    unit: str = "nm",
) -> DataStruct:
    """A calibrated raster with structure (a stitch/montage input)."""
    rng = np.random.default_rng(seed)
    data = rng.normal(size=(h, w)) + np.linspace(0.0, 5.0, w)[None, :]
    cal = AxisCal(scale, 0.0, unit)
    return DataStruct(
        data=data,
        kind=DataKind.IMAGE,
        axes=(cal, cal),
        metadata={"source": source} if source else {},
    )


def _tiles(n: int = 3) -> list[DataStruct]:
    return [_image(seed=i, source=f"frame_{i}") for i in range(n)]


# ── stitch ────────────────────────────────────────────────────────────


def test_stitch_matches_the_calc_function() -> None:
    tiles = _tiles(3)
    result = ops.run(
        "stitch",
        tiles[0],
        {"layout": "horizontal", "overlap_frac": 0.25, "blend_width": 8.0},
        inputs={"others": tiles[1:]},
    )
    expected = stitch_images(
        [t.data for t in tiles],
        layout="horizontal",
        overlap_frac=0.25,
        blend_width=8.0,
    )
    np.testing.assert_allclose(result.derived.data, expected.mosaic)
    assert result.derived.metadata["offsets"] == expected.offsets.tolist()
    assert result.derived.metadata["layout"] == expected.layout
    assert result.derived.metadata["n_images"] == 3
    # the mosaic keeps the subject's (tile 1's) spatial calibration
    assert result.derived.axes == (tiles[0].axes[0], tiles[0].axes[1])


def test_stitch_auto_layout_resolves_in_the_metadata() -> None:
    """'auto' is resolved by calc, so the RECORDED layout is the chosen
    orientation — the route returns the same resolved string."""
    tiles = _tiles(2)
    result = ops.run(
        "stitch", tiles[0], {"layout": "auto"}, inputs={"others": tiles[1:]}
    )
    expected = stitch_images([t.data for t in tiles], layout="auto")
    assert result.derived.metadata["layout"] == expected.layout
    assert result.derived.metadata["layout"] in ("horizontal", "vertical")
    assert result.params["layout"] == "auto"  # the request, for reproduction


def test_stitch_rejects_unequal_tiles() -> None:
    """routes/structure.py's 'stitch requires equal-size tiles' 422 stays
    route-side, so the op reproduces the precondition itself: calc sizes its
    canvas from the FIRST tile, and mismatched tiles would silently crop."""
    subject = _image()
    with pytest.raises(ValueError, match="equal-size tiles"):
        ops.run("stitch", subject, inputs={"others": [_image(h=20, w=32)]})


def test_stitch_needs_a_second_tile_like_its_route() -> None:
    """The route's 'need at least 2 images to stitch' is the input schema's
    min_count here (the subject is tile 1)."""
    with pytest.raises(InputError, match="at least 1 dataset"):
        ops.run("stitch", _image(), inputs={"others": []})


def test_stitch_mirrors_the_routes_bounds() -> None:
    tiles = _tiles(2)
    with pytest.raises(ParamError, match=r"0\.6 > max 0\.5"):
        ops.run("stitch", tiles[0], {"overlap_frac": 0.6}, inputs={"others": tiles[1:]})
    with pytest.raises(ParamError, match="not in"):
        ops.run(
            "stitch", tiles[0], {"layout": "diagonal"}, inputs={"others": tiles[1:]}
        )


# ── montage ───────────────────────────────────────────────────────────


def test_montage_matches_the_calc_function() -> None:
    tiles = _tiles(3)
    params = {"cols": 2, "gap": 6, "bg": -1.0, "font_size": 10}
    result = ops.run("montage", tiles[0], params, inputs={"others": tiles[1:]})
    expected = calc_montage(
        [t.data for t in tiles],
        cols=2,
        labels=["frame_0", "frame_1", "frame_2"],
        gap=6,
        bg=-1.0,
        overlap=0.0,
        font_size=10,
    )
    np.testing.assert_allclose(result.derived.data, expected)
    assert result.derived.metadata["n_tiles"] == 3


def test_montage_labels_come_from_metadata_source() -> None:
    """The route composes labels from ``store.name(image_id)``; a pure op has
    no session store, so ADR 0005 §8 letters its inputs from each dataset's
    ``metadata['source']``. Same pixels as calc called with those strings —
    and different pixels from the unlabelled montage, i.e. the labels really
    are baked."""
    tiles = [_image(seed=0, source="anneal_400C"), _image(seed=1, source="as_grown")]
    result = ops.run("montage", tiles[0], inputs={"others": tiles[1:]})
    assert result.derived.metadata["tile_labels"] == ["anneal_400C", "as_grown"]
    expected = calc_montage(
        [t.data for t in tiles], labels=["anneal_400C", "as_grown"]
    )
    np.testing.assert_allclose(result.derived.data, expected)
    bare = ops.run("montage", tiles[0], {"labels": False}, inputs={"others": tiles[1:]})
    assert not np.allclose(bare.derived.data, result.derived.data)
    np.testing.assert_allclose(bare.derived.data, calc_montage([t.data for t in tiles]))
    assert bare.derived.metadata["tile_labels"] == []


def test_montage_labels_fall_back_to_the_tile_position() -> None:
    """A struct with no ``source`` still gets a caption — never a blank one."""
    result = ops.run(
        "montage", _image(seed=3), inputs={"others": [_image(seed=4)]}
    )
    assert result.derived.metadata["tile_labels"] == ["tile 1", "tile 2"]


def test_montage_overlap_rejects_one_but_accepts_just_under() -> None:
    """The route's ``Field(ge=0.0, lt=1.0)``, spelled as the contract's
    exclusive maximum (ADR 0005 §9) instead of a hand-written ValueError."""
    tiles = _tiles(2)
    with pytest.raises(ParamError, match=r"1\.0 must be < 1\.0"):
        ops.run("montage", tiles[0], {"overlap": 1.0}, inputs={"others": tiles[1:]})
    with pytest.raises(ParamError, match="must be < 1.0"):
        ops.run("montage", tiles[0], {"overlap": 1.5}, inputs={"others": tiles[1:]})
    with pytest.raises(ParamError, match=r"-0\.1 < min"):
        ops.run("montage", tiles[0], {"overlap": -0.1}, inputs={"others": tiles[1:]})
    ok = ops.run("montage", tiles[0], {"overlap": 0.999}, inputs={"others": tiles[1:]})
    np.testing.assert_allclose(
        ok.derived.data,
        calc_montage(
            [t.data for t in tiles],
            labels=["frame_0", "frame_1"],
            overlap=0.999,
        ),
    )


def test_montage_cols_sentinel_is_the_routes_null() -> None:
    """``cols`` is a NaN-sentinel float: unset means the route's ``null``
    (ceil(sqrt(n))), a whole number means that many columns, and a
    fractional one is refused rather than truncated."""
    tiles = _tiles(4)
    auto = ops.run("montage", tiles[0], inputs={"others": tiles[1:]})
    labels = [f"frame_{i}" for i in range(4)]
    np.testing.assert_allclose(
        auto.derived.data, calc_montage([t.data for t in tiles], labels=labels)
    )
    # 4 frames: auto is a 2x2 grid, cols=1 is a single column — different shapes
    one = ops.run("montage", tiles[0], {"cols": 1}, inputs={"others": tiles[1:]})
    np.testing.assert_allclose(
        one.derived.data,
        calc_montage([t.data for t in tiles], cols=1, labels=labels),
    )
    assert one.derived.data.shape != auto.derived.data.shape
    with pytest.raises(ValueError, match="whole number"):
        ops.run("montage", tiles[0], {"cols": 2.5}, inputs={"others": tiles[1:]})


def test_montage_tiles_a_lone_subject_like_its_route() -> None:
    """``/analyze/montage`` accepts a single image id, so ``others`` is an
    optional variadic input rather than a required one."""
    result = ops.run("montage", _image(source="only"))
    np.testing.assert_allclose(
        result.derived.data, calc_montage([_image(source="only").data], labels=["only"])
    )


# ── montage_compare ───────────────────────────────────────────────────


def _compare_tiles() -> list[DataStruct]:
    """Three tiles at DIFFERENT pixel sizes — the whole point of the op."""
    return [
        _image(h=40, w=40, seed=0, source="fine", scale=1.0, unit="um"),
        _image(h=20, w=20, seed=1, source="coarse", scale=4.0, unit="um"),
        _image(h=30, w=30, seed=2, source="mid", scale=2.0, unit="um"),
    ]


def test_montage_compare_matches_the_calc_function() -> None:
    tiles = _compare_tiles()
    meta = [
        {"label": "300 C", "param_value": 300.0},
        {"label": "", "param_value": 100.0},
        {"label": "200 C", "param_value": 200.0},
    ]
    result = ops.run(
        "montage_compare",
        tiles[0],
        {"tile_meta": meta, "cols": 3, "gap": 2, "font_size": 8},
        inputs={"tiles": tiles[1:]},
    )
    order = order_by_param_value([300.0, 100.0, 200.0])
    assert order == [1, 2, 0]  # ascending by param_value, as the route sorts
    labels = ["coarse", "200 C", "300 C"]  # tile 1's blank label -> its source
    expected = montage_physical_scale(
        [tiles[i].data for i in order],
        [tiles[i].pixel_size for i in order],
        [tiles[i].pixel_unit for i in order],
        labels=labels,
        cols=3,
        gap=2,
        font_size=8,
    )
    np.testing.assert_allclose(result.derived.data, expected.canvas)
    assert result.derived.metadata["tile_labels"] == labels
    assert result.derived.metadata["n_tiles"] == 3
    assert result.derived.metadata["scale_bar"] == {
        "x": expected.scale_bar.x,
        "y": expected.scale_bar.y,
        "width": expected.scale_bar.width,
        "height": expected.scale_bar.height,
        "label": expected.scale_bar.label,
        "color": expected.scale_bar.color,
    }
    # the canvas is calibrated in the COMMON (coarsest) scale, not the
    # subject's — the calibration the route registers
    assert result.derived.axes[0].scale == expected.pixel_size
    assert result.derived.axes[0].units == expected.pixel_unit
    assert expected.pixel_size == 4.0


def test_param_value_is_any_scalar_so_strings_and_bools_sink_to_the_back() -> None:
    """CRITICAL, and the reason ``param_value``'s ptype is ``ANY_SCALAR``:
    ``order_by_param_value`` treats a numeric-LOOKING string ("300") and a
    bool as CATEGORICAL — they keep request order behind every real number.
    A ``float`` ptype would parse "300" into the numeric bucket and a ``str``
    ptype would push 3.37 out of it; either way the op would tile the panel
    in a different order than the route does for the same request."""
    tiles = _compare_tiles()
    meta = [
        {"label": "num", "param_value": 300.0},
        {"label": "str", "param_value": "300"},
        {"label": "flag", "param_value": True},
    ]
    result = ops.run(
        "montage_compare", tiles[0], {"tile_meta": meta}, inputs={"tiles": tiles[1:]}
    )
    # the route's own ordering call, on the values the route would hold
    assert order_by_param_value([300.0, "300", True]) == [0, 1, 2]
    assert result.derived.metadata["tile_labels"] == ["num", "str", "flag"]
    # ... and the string/bool really are behind the numerics, not merely in
    # request order by luck: a smaller number jumps ahead of both
    meta[0]["param_value"] = 3.37
    meta.append({"label": "late", "param_value": 1.0})
    late = ops.run(
        "montage_compare",
        tiles[0],
        {"tile_meta": meta},
        inputs={"tiles": [*tiles[1:], _image(seed=9, source="d", scale=3.0, unit="um")]},
    )
    assert late.derived.metadata["tile_labels"] == ["late", "num", "str", "flag"]
    # the resolved params keep the values verbatim — no coercion happened
    assert late.params["tile_meta"][1]["param_value"] == "300"
    assert late.params["tile_meta"][2]["param_value"] is True


def test_montage_compare_orders_in_request_order_without_param_values() -> None:
    """No ``tile_meta`` at all: request order, captions from metadata —
    the route's pre-item-29 behaviour."""
    tiles = _compare_tiles()
    result = ops.run("montage_compare", tiles[0], inputs={"tiles": tiles[1:]})
    assert result.derived.metadata["tile_labels"] == ["fine", "coarse", "mid"]
    expected = montage_physical_scale(
        [t.data for t in tiles],
        [t.pixel_size for t in tiles],
        [t.pixel_unit for t in tiles],
        labels=["fine", "coarse", "mid"],
    )
    np.testing.assert_allclose(result.derived.data, expected.canvas)


def test_montage_compare_refuses_an_uncalibrated_tile() -> None:
    """The route's 422: a common physical scale is undefined, and tiling
    anyway would bake a scale bar that is wrong for some tiles."""
    tiles = _compare_tiles()
    blind = DataStruct(
        data=np.ones((10, 10)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(1.0, 0.0, ""), AxisCal(1.0, 0.0, "")),
        metadata={"source": "uncalibrated"},
    )
    with pytest.raises(ValueError, match="uncalibrated.*no pixel calibration"):
        ops.run("montage_compare", tiles[0], inputs={"tiles": [blind]})


def test_montage_compare_tile_meta_must_cover_every_tile() -> None:
    tiles = _compare_tiles()
    with pytest.raises(ValueError, match="one record per tile"):
        ops.run(
            "montage_compare",
            tiles[0],
            {"tile_meta": [{"label": "only one"}]},
            inputs={"tiles": tiles[1:]},
        )


def test_montage_compare_tile_meta_rejects_containers_and_unknown_fields() -> None:
    """ANY_SCALAR is 'any scalar', not 'anything' (ADR 0005 §9)."""
    tiles = _compare_tiles()
    with pytest.raises(ParamError, match="expected a number, string, bool or null"):
        ops.run(
            "montage_compare",
            tiles[0],
            {"tile_meta": [{"param_value": [1, 2]}, {}, {}]},
            inputs={"tiles": tiles[1:]},
        )
    with pytest.raises(ParamError, match="unknown param"):
        ops.run(
            "montage_compare",
            tiles[0],
            {"tile_meta": [{"image_id": "img-1"}, {}, {}]},
            inputs={"tiles": tiles[1:]},
        )


def test_the_three_ops_declare_their_inputs_and_arity() -> None:
    """Each is a §8 multi-input op: one subject, the rest named."""
    for name, input_name in (
        ("stitch", "others"),
        ("montage", "others"),
        ("montage_compare", "tiles"),
    ):
        spec = ops.get_spec(name)
        assert spec.multi_input
        assert list(spec.inputs) == [input_name]
        assert spec.inputs[input_name].variadic
