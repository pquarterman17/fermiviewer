"""4C-4 — layer and structural analyses over canonical regions.

The oracle for a masked collapse is `statistics.fmean` / `statistics.median`
over pixel lists built by hand, not numpy and not the code under test: a
per-depth average is exactly the kind of claim that a test written with
the same expression it is checking will confirm no matter what.

The refusals get the same treatment as the numbers. `reduce="sum"` over an
irregular region is refused because the profile would follow the region's
WIDTH, and that is asserted as a demonstrated fact — the summed profile of
a flat specimen through a circle really does produce flanks a detector
reads as interfaces — rather than as an assumption in a docstring.
"""

from __future__ import annotations

import statistics
from typing import Any

import numpy as np
import pytest

import fermiviewer.ops as ops
from fermiviewer.calc.layers import analyze_layers
from fermiviewer.calc.layers_profile import cross_section_profile
from fermiviewer.calc.region_profile import masked_depth_profile
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct

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


def _stack(n_rows: int = 40, n_cols: int = 40) -> np.ndarray:
    """A three-layer cross-section: two interfaces at rows 13 and 26."""
    img = np.zeros((n_rows, n_cols))
    img[13:26, :] = 50.0
    img[26:, :] = 100.0
    return img


# ── the masked collapse ──────────────────────────────────────────────


def _profile_by_hand(block: np.ndarray, window: np.ndarray, axis: str, reduce: str) -> list[float]:
    """Expected profile, from the written definition, in pure Python."""
    rows, cols = block.shape
    out: list[float] = []
    outer = range(rows) if axis == "y" else range(cols)
    inner = range(cols) if axis == "y" else range(rows)
    for i in outer:
        picked = [
            float(block[i, j] if axis == "y" else block[j, i])
            for j in inner
            if (window[i, j] if axis == "y" else window[j, i])
        ]
        out.append(statistics.fmean(picked) if reduce == "mean" else statistics.median(picked))
    return out


@pytest.mark.parametrize("reduce", ["mean", "median"])
@pytest.mark.parametrize("axis", ["y", "x"])
def test_the_masked_collapse_averages_only_selected_pixels(axis: str, reduce: str) -> None:
    rng = np.random.default_rng(11)
    block = rng.normal(30.0, 7.0, (9, 11))
    window = rng.random((9, 11)) > 0.35
    window[:, 0] = True  # every row keeps something
    window[0, :] = True  # every column too

    pos, profile = masked_depth_profile(block, window, axis, reduce)
    expected = _profile_by_hand(block, window, axis, reduce)
    assert pos.tolist() == list(range(len(expected)))
    assert profile.tolist() == pytest.approx(expected, rel=1e-12)


def test_an_all_true_mask_reproduces_the_rectangular_collapse() -> None:
    """The masked path and the golden `box_integrate` path must agree
    wherever both are defined, or a region that happens to be rectangular
    would answer differently depending on how it was spelled."""
    img = _stack()
    window = np.ones_like(img, dtype=bool)
    _, masked = masked_depth_profile(img, window, "y", "mean")
    _, legacy = cross_section_profile(img, None, "y", "mean")
    assert masked.tolist() == pytest.approx(legacy.tolist(), rel=1e-12)


def test_a_nonfinite_pixel_is_excluded_rather_than_propagated() -> None:
    block = np.array([[1.0, 2.0, np.nan], [4.0, 5.0, 6.0]])
    window = np.ones((2, 3), dtype=bool)
    _, profile = masked_depth_profile(block, window, "y", "mean")
    assert profile[0] == pytest.approx(1.5), "the NaN column drops out of the mean"
    assert profile[1] == pytest.approx(5.0)


def test_sum_is_refused_over_an_irregular_region() -> None:
    with pytest.raises(ValueError, match="reduce='mean'"):
        masked_depth_profile(
            np.ones((3, 3)),
            np.array([[1, 1, 0], [1, 1, 1], [0, 1, 1]], dtype=bool),
            "y",
            "sum",
        )


def test_summing_over_a_varying_width_really_does_invent_interfaces() -> None:
    """The refusal above, justified rather than asserted.

    A perfectly FLAT specimen — one constant value everywhere, no
    interface anywhere — summed through a circular region produces a
    profile whose flanks are as steep as any real interface. The refusal
    exists because this number is wrong, not because it is unusual.
    """
    flat = np.ones((41, 41))
    rows = np.arange(41)[:, None]
    cols = np.arange(41)[None, :]
    circle = (rows - 20) ** 2 + (cols - 20) ** 2 <= 20**2

    summed = np.sum(np.where(circle, flat, 0.0), axis=1)
    averaged = np.sum(flat, axis=1, where=circle) / circle.sum(axis=1)

    assert summed.max() / summed.min() > 4, (
        "the summed profile of a FLAT specimen swings by more than 4x — "
        "entirely from the region's width"
    )
    assert averaged.max() == pytest.approx(averaged.min()), (
        "the mean sees the specimen: flat in, flat out"
    )


def test_a_depth_with_no_selected_pixel_is_refused() -> None:
    window = np.ones((3, 3), dtype=bool)
    window[1, :] = False  # the middle depth keeps nothing
    with pytest.raises(ValueError, match="depth 1 with no usable pixel"):
        masked_depth_profile(np.ones((3, 3)), window, "y", "mean")


def test_the_masked_collapse_rejects_bad_shapes_and_modes() -> None:
    with pytest.raises(ValueError, match="does not match the region"):
        masked_depth_profile(np.ones((3, 3)), np.ones((2, 2), dtype=bool), "y", "mean")
    with pytest.raises(ValueError, match="axis must be"):
        masked_depth_profile(np.ones((3, 3)), np.ones((3, 3), dtype=bool), "z", "mean")
    with pytest.raises(ValueError, match="reduce must be"):
        masked_depth_profile(np.ones((3, 3)), np.ones((3, 3), dtype=bool), "y", "geometric")


# ── layers ───────────────────────────────────────────────────────────


def test_layers_rect_region_reproduces_the_legacy_roi_string() -> None:
    ds = _image(_stack())
    legacy = ops.run("layers", ds, {"roi": "1,1,40,30", "axis": "y"})
    migrated = ops.run(
        "layers",
        ds,
        {"region": [{"kind": "rect", "bounds": [[0, 0, 39, 29]]}], "axis": "y"},
    )
    assert _named(legacy, "depth_profile") == _named(migrated, "depth_profile")


def test_layers_over_an_ellipse_still_finds_the_interfaces() -> None:
    """The point of the wave: a region drawn around the stack must still
    measure the stack. The mean collapse keeps the interfaces where a sum
    would have buried them under the region's width."""
    ds = _image(_stack())
    run = ops.run(
        "layers",
        ds,
        {"region": [{"kind": "ellipse", "bounds": [[0, 0, 39, 39]]}], "axis": "y"},
    )
    positions = [
        o["data"]["coefficients"]["position"]
        for o in run.value["outputs"]
        if o["name"].startswith("interface_")
    ]
    assert len(positions) == 2
    assert positions == pytest.approx([13.0, 26.0], abs=1.5)
    assert _named(run, "region")["exact_mask"] is True
    assert _named(run, "region")["label_context"] == "exact-mask"


def test_layers_reports_no_region_when_unscoped() -> None:
    assert not _has(ops.run("layers", _image(_stack()), {"axis": "y"}), "region")


def test_layers_refuses_two_scopes_and_refuses_sum_over_a_mask() -> None:
    ds = _image(_stack())
    with pytest.raises(ValueError, match="not both"):
        ops.run(
            "layers",
            ds,
            {"roi": "1,1,40,40", "region": [{"kind": "rect", "bounds": [[0, 0, 39, 39]]}]},
        )
    with pytest.raises(ValueError, match="reduce='mean'"):
        ops.run(
            "layers",
            ds,
            {
                "region": [{"kind": "ellipse", "bounds": [[0, 0, 39, 39]]}],
                "reduce": "sum",
                "axis": "y",
            },
        )


def test_a_rectangular_region_still_allows_sum() -> None:
    """The refusal is about VARYING support, not about regions. A rect
    region has uniform support, so it keeps every mode the ROI string had
    — otherwise the migration would have removed a capability."""
    ds = _image(_stack())
    run = ops.run(
        "layers",
        ds,
        {"region": [{"kind": "rect", "bounds": [[0, 0, 39, 39]]}], "reduce": "sum", "axis": "y"},
    )
    legacy = ops.run("layers", ds, {"reduce": "sum", "axis": "y"})
    assert _named(run, "depth_profile") == _named(legacy, "depth_profile")


def test_waviness_tracing_is_refused_over_an_irregular_region() -> None:
    """Roughness metrology over a drawn outline would measure the
    outline. The refusal names the way out."""
    with pytest.raises(ValueError, match="waviness"):
        analyze_layers(
            _stack(),
            roi=(1, 1, 40, 40),
            mask=np.ones((40, 40), dtype=bool),
            axis="y",
            waviness=True,
        )


def test_layers_edit_takes_the_same_region() -> None:
    ds = _image(_stack())
    run = ops.run(
        "layers_edit",
        ds,
        {
            "positions": "13,26",
            "axis": "y",
            "region": [{"kind": "ellipse", "bounds": [[0, 0, 39, 39]]}],
        },
    )
    assert len(_named(run, "layers")["rows"]) >= 1


# ── structural: efd_similarity shares the particle path ──────────────


def _two_shapes() -> np.ndarray:
    img = np.zeros((40, 40))
    img[4:12, 4:12] = 10.0  # square
    img[25:33, 25:33] = 10.0
    return img


def test_efd_similarity_scopes_through_the_same_helper_as_particles() -> None:
    """Both ops segment with `particle_analysis`, so scoping them
    differently would mean a region selected different particles
    depending on which op you asked — the divergence 4C exists to stop."""
    ds = _image(_two_shapes())
    region = [{"kind": "rect", "bounds": [[0, 0, 20, 20]]}]
    scoped = ops.run("efd_similarity", ds, {"ref_id": 1, "region": region})
    assert _named(scoped, "region")["rows"] == [[1, 1, 21, 21]]
    whole = ops.run("efd_similarity", ds, {"ref_id": 1})
    # the ranking lists the reference itself at distance 0, so the counts
    # are "how many particles were segmented at all": the region halves it
    assert len(_named(whole, "ranked")["rows"]) == 2
    assert len(_named(scoped, "ranked")["rows"]) == 1


def test_efd_similarity_auto_threshold_ignores_pixels_outside_the_mask() -> None:
    """Same claim as `particles`, asserted for this op too rather than
    assumed from the shared helper: the helper could be called with the
    wrong arguments here and nothing else would notice."""
    region = [{"kind": "ellipse", "bounds": [[0, 0, 24, 24]]}]

    def ranked(img: np.ndarray) -> int:
        run = ops.run("efd_similarity", _image(img), {"ref_id": 1, "region": region})
        return len(_named(run, "ranked")["rows"])

    base = _two_shapes()
    hot = base.copy()
    hot[0:2, 0:2] = 5000.0  # in the bounding box, outside the ellipse
    assert ranked(hot) == ranked(base)
