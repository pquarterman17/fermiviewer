"""Synthetic reference tests for reviewed layer/grain spatial assignment."""

import numpy as np
import pytest

from fermiviewer.calc.grain_layers import LayerBounds, measure_grains_by_layer


@pytest.mark.imaging
def test_measures_grain_slices_in_horizontal_layers() -> None:
    labels = np.zeros((8, 8), dtype=np.int32)
    labels[0:4, 0:3] = 1
    labels[0:6, 4:8] = 2  # deliberately crosses the material interface
    labels[4:8, 0:4] = 3
    result = measure_grains_by_layer(
        labels,
        [LayerBounds(0, 0.0, 4.0), LayerBounds(1, 4.0, 8.0)],
        selected_indices=[0, 1], axis="y", pixel_size=0.5, unit="nm",
    )

    assert result.axis == "y"
    assert len(result.layers) == 2
    top, bottom = result.layers
    assert top.n_grains == 2
    assert top.area_px == 32
    assert top.occupied_fraction == pytest.approx(28 / 32)
    assert top.mean_lateral_width == pytest.approx(1.75)
    assert top.mean_depth_height == pytest.approx(2.0)
    assert top.cross_layer_grains == 1
    assert bottom.n_grains == 2
    assert bottom.cross_layer_grains == 1
    assert np.all(result.assignment[labels == 1] == 1)
    assert np.all(result.assignment[labels == 3] == 2)


@pytest.mark.imaging
def test_axis_roi_and_traces_define_local_layer_mask() -> None:
    labels = np.zeros((6, 10), dtype=np.int32)
    labels[1:5, 2:8] = 7
    result = measure_grains_by_layer(
        labels,
        [LayerBounds(0, 1.0, 5.0)],
        selected_indices=[0], axis="x", roi=(2, 3, 5, 8),
        interface_traces=[np.array([0.0, 1.0, 1.0, 0.0]),
                          np.array([4.0, 3.0, 3.0, 4.0])],
    )

    layer = result.layers[0]
    assert layer.n_grains == 1
    assert layer.area_px == 12
    assert layer.grains[0].area_px == 12
    assert np.count_nonzero(result.assignment) == 12
    assert not np.any(result.assignment[[0, 5], :])


@pytest.mark.imaging
def test_requires_a_valid_selected_layer() -> None:
    labels = np.ones((4, 4), dtype=np.int32)
    with pytest.raises(ValueError, match="select at least one"):
        measure_grains_by_layer(
            labels, [LayerBounds(0, 0.0, 4.0)],
            selected_indices=[], axis="y",
        )
    with pytest.raises(ValueError, match="trace length"):
        measure_grains_by_layer(
            labels, [LayerBounds(0, 0.0, 4.0)],
            selected_indices=[0], axis="y",
            interface_traces=[np.ones(3), np.ones(3)],
        )
