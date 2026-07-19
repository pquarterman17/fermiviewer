import numpy as np
import pytest

from fermiviewer.calc.roi import (
    embed_rect_roi,
    extract_rect_roi,
    parse_rect_roi,
    roi_slices,
)


def test_roi_slices_are_one_based_inclusive_clamped_and_order_independent() -> None:
    assert roi_slices((8, 10), (7, 9, 2, 3)) == (slice(1, 7), slice(2, 9))
    assert roi_slices((8, 10), (-4, 3, 50, 30)) == (slice(0, 8), slice(2, 10))


def test_extract_and_embed_round_trip() -> None:
    image = np.arange(48).reshape(6, 8)
    roi = (2, 3, 5, 7)
    crop = extract_rect_roi(image, roi)
    assert crop.shape == (4, 5)
    embedded = embed_rect_roi(crop, image.shape, roi)
    assert np.array_equal(embedded[1:5, 2:7], crop)
    assert np.count_nonzero(embedded[:1]) == 0
    assert np.count_nonzero(embedded[:, :2]) == 0


def test_roi_outside_image_and_wrong_result_shape_are_rejected() -> None:
    with pytest.raises(ValueError, match="does not overlap"):
        roi_slices((8, 10), (20, 20, 30, 30))
    with pytest.raises(ValueError, match="does not match"):
        embed_rect_roi(np.zeros((2, 2)), (8, 10), (1, 1, 4, 4))


def test_parse_rect_roi_requires_exactly_four_values() -> None:
    assert parse_rect_roi("1,2,30,40") == (1, 2, 30, 40)
    assert parse_rect_roi("1,2,3") is None
    assert parse_rect_roi([1, 2, 3, 4]) is None
