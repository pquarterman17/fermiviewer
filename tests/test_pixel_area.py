"""An area is two scales multiplied, not one scale squared.

`DataStruct.pixel_cal` returns the SECOND spatial axis, and every area in
the tree used to be `pixel_size ** 2`. That is right only when the two
spatial scales agree, and they do not have to: `io/nanoscope` builds them
from `y_nm / ny` and `x_nm / nx` independently, so an AFM scan with 0.5 nm
rows against 2.0 nm columns reported four times the true area.

These tests pin the corrected rule at the property and at every consumer
that reports an area, because the value of a shared rule is that the
consumers cannot disagree — which is exactly what a per-consumer fix
would have destroyed.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.profile_stats import roi_stats
from fermiviewer.calc.region_stats import region_stats
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


def _image(rows: float, cols: float, unit: str = "nm") -> DataStruct:
    return DataStruct(
        data=np.zeros((40, 60)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(scale=rows, units=unit), AxisCal(scale=cols, units=unit)),
        metadata={},
    )


# ── the property ─────────────────────────────────────────────────────


def test_an_anisotropic_pixel_is_not_its_length_squared() -> None:
    """The defect, stated as the number it produced. 0.5 x 2.0 is 1.0 nm^2
    per pixel; squaring `pixel_size` (the second axis) gave 4.0."""
    ds = _image(0.5, 2.0)
    assert ds.pixel_size == 2.0
    assert ds.pixel_size**2 == 4.0
    assert ds.pixel_area == 1.0


def test_square_pixels_are_unchanged() -> None:
    """The overwhelmingly common case must produce exactly what it always
    did, or this correction would be a silent renumbering of everyone's
    published results rather than a fix for the few who were wrong."""
    for scale in (0.25, 1.0, 7.5):
        ds = _image(scale, scale)
        assert ds.pixel_area == pytest.approx(ds.pixel_size**2)


def test_a_negative_scale_still_gives_a_positive_area() -> None:
    """A negative scale is a direction convention — DM writes them — and
    an area has no direction. The squared form absorbed that by accident;
    the product has to do it on purpose."""
    assert _image(-0.5, 2.0).pixel_area == 1.0
    assert _image(-0.5, -2.0).pixel_area == 1.0


def test_mismatched_units_have_no_area_rather_than_a_guessed_one() -> None:
    """nm times um is a number in neither unit. Absent beats invented
    (ADR 0004) — and the `unit` field could only name one of them."""
    ds = DataStruct(
        data=np.zeros((4, 4)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(scale=0.5, units="nm"), AxisCal(scale=2.0, units="um")),
        metadata={},
    )
    assert np.isfinite(ds.pixel_size), "the length is still well defined"
    assert np.isnan(ds.pixel_area)


@pytest.mark.parametrize(
    "rows",
    [
        AxisCal(),                          # no scale, no unit
        AxisCal(scale=0.0, units="nm"),     # a unit, but scale 0 is uncalibrated
        AxisCal(scale=float("nan"), units="nm"),
    ],
)
def test_one_uncalibrated_axis_is_enough_to_have_no_area(rows: AxisCal) -> None:
    """BOTH axes are required, and the middle case is the one that proves
    it: its unit matches, so the unit check cannot reject it and only the
    calibration test can. Without it, `and` could weaken to `or` and every
    assertion here would still pass."""
    ds = DataStruct(
        data=np.zeros((4, 4)),
        kind=DataKind.IMAGE,
        axes=(rows, AxisCal(scale=2.0, units="nm")),
        metadata={},
    )
    assert np.isnan(ds.pixel_area)


def test_a_spectrum_has_no_pixel_area() -> None:
    """Same refusal as `pixel_cal`, for the same reason: no spatial axes."""
    ds = DataStruct(data=np.arange(5.0), kind=DataKind.SPECTRUM, axes=(AxisCal(),))
    with pytest.raises(ValueError, match="no spatial axes"):
        _ = ds.pixel_area


# ── every consumer agrees, and all of them are right ─────────────────


def test_the_area_consumers_agree_on_an_anisotropic_image(client) -> None:
    """The property a per-consumer fix would have broken.

    `/regions/preview` and `/measure/roi` reach an area by different
    routes — one counts a resolved mask, the other reduces over it — so
    agreeing is evidence. Both must also be RIGHT: 100 pixels of
    0.5 x 2.0 nm is 100 nm^2, where the squared form said 400.
    """
    image_id = store.add_parsed(_image(0.5, 2.0), "afm.dm4")
    preview = client.post(
        "/api/regions/preview", json={"image_id": image_id, "roi": "1,1,10,10"}
    ).json()
    measured = client.post(
        "/api/measure/roi", json={"image_id": image_id, "rect": [1, 1, 10, 10]}
    ).json()

    assert preview["pixel_count"] == 100
    assert preview["area_calibrated"] == pytest.approx(100.0)
    assert measured["area"] == pytest.approx(100.0)
    assert preview["area_calibrated"] == pytest.approx(measured["area"])


def test_the_calc_layer_takes_an_area_not_a_length(client) -> None:
    """`region_stats` and `roi_stats` name the parameter `pixel_area`
    precisely so a caller cannot pass a length and get a plausible wrong
    answer. Pinned as a contract: the area is the count times the value
    handed in, with no squaring anywhere."""
    img = np.ones((10, 10))
    assert region_stats(img, (1, 1, 5, 5), pixel_area=1.0)["area"] == 25.0
    assert roi_stats(img, 1, 1, 5, 5, pixel_area=1.0)["area"] == 25.0
    # a 0.5 x 2.0 pixel: 25 of them cover 25 nm^2, not 100
    assert region_stats(img, (1, 1, 5, 5), pixel_area=0.5 * 2.0)["area"] == 25.0
