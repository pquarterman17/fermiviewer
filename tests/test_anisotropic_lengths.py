"""Lengths on non-square pixels, end to end.

`pixel_area` (PR #200) fixed AREAS: an area is two scales multiplied, not
one squared. Lengths were left assuming square pixels — equivalent
diameter, Feret, perimeter and the moment-ellipse axes all came from a
single `pixel_size`, and every dimensionless shape descriptor was
computed in the distorted pixel space rather than on the particle.

These pin the corrected behaviour at the API, not just in `calc`, and
they pin the far more important half of the contract too: on SQUARE
pixels nothing moves at all. A correction that silently renumbers every
existing isotropic result is not a correction.

The fixture is a physically CIRCULAR disc sampled on 3:1 pixels. It is
chosen because the two readings disagree qualitatively rather than in
the third decimal: in pixel space it is an ellipse of aspect ratio ~3
and classifies as rod-like; physically it is a sphere.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from skimage import draw

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.project_session import project
from fermiviewer.server import ALLOWED_HOSTS, create_app
from fermiviewer.session import store

pytestmark = pytest.mark.api

ALLOWED_HOSTS.add("testserver")

#: physical extent of one pixel, (row, column) — rows 3x coarser
ROW_NM, COL_NM = 3.0, 1.0
#: physical radius of the disc, in nm
RADIUS_NM = 30.0


@pytest.fixture()
def client():
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


def _disc_image(row_nm: float, col_nm: float) -> DataStruct:
    """A physically circular disc of radius RADIUS_NM, sampled on a grid
    of the given anisotropy. Fewer rows than columns when rows are the
    coarser axis, which is exactly what makes it an ellipse in the array.
    """
    n_r, n_c = int(RADIUS_NM / row_nm), int(RADIUS_NM / col_nm)
    img = np.zeros((2 * n_r + 24, 2 * n_c + 24), dtype=np.float64)
    rr, cc = draw.ellipse(n_r + 12, n_c + 12, n_r, n_c)
    img[rr, cc] = 100.0
    return DataStruct(
        data=img,
        kind=DataKind.IMAGE,
        axes=(AxisCal(scale=row_nm, units="nm"), AxisCal(scale=col_nm, units="nm")),
        metadata={},
    )


def _particle(client: TestClient, ds: DataStruct) -> dict:
    image_id = store.add_parsed(ds, "aniso.dm4")
    r = client.post(
        "/api/analyze/particles",
        json={"image_id": image_id, "threshold": 50, "min_area": 20},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_particles"] == 1, body["n_particles"]
    return body["particles"][0]


# ── the correction ───────────────────────────────────────────────────────


def test_a_round_particle_on_3to1_pixels_is_not_a_rod(client) -> None:
    """The defect stated as the answer it produced.

    Measured in pixel space this disc has aspect ratio ~3.0 and
    eccentricity ~0.94 — the shape of the SAMPLING, not of the particle,
    and enough to classify a sphere as a rod.
    """
    p = _particle(client, _disc_image(ROW_NM, COL_NM))
    assert p["aspect_ratio"] == pytest.approx(1.0, abs=0.15)
    assert p["eccentricity"] < 0.45
    assert p["circularity"] == pytest.approx(1.0, abs=0.15)
    assert p["shape_class"] != "rod-like"


def test_calibrated_feret_is_the_physical_diameter(client) -> None:
    """`feret_max_calibrated` must be the disc's real diameter.

    The old route computed `feret_max_px * pixel_size`, which uses the
    column scale for a distance that is mostly along rows. The oracle
    here is 2*RADIUS_NM — geometry, not another code path.
    """
    p = _particle(client, _disc_image(ROW_NM, COL_NM))
    assert p["feret_max_calibrated"] == pytest.approx(2 * RADIUS_NM, rel=0.10)
    # and it is NOT the old single-scale product, which this fixture makes
    # visibly different from the truth
    assert p["feret_max_calibrated"] != pytest.approx(p["feret_max"] * COL_NM, rel=1e-6)


def test_the_same_disc_measures_the_same_at_a_different_anisotropy(client) -> None:
    """Sampling is not a property of the particle. The same physical disc
    on 3:1 and on 1:3 pixels must return the same physical diameter."""
    tall = _particle(client, _disc_image(3.0, 1.0))
    store.clear()
    wide = _particle(client, _disc_image(1.0, 3.0))
    assert tall["feret_max_calibrated"] == pytest.approx(
        wide["feret_max_calibrated"], rel=0.10
    )
    assert tall["aspect_ratio"] == pytest.approx(wide["aspect_ratio"], abs=0.15)


# ── the half that matters more: square pixels must not move ──────────────


def test_square_pixels_are_untouched(client) -> None:
    """Every dimensionless descriptor on square pixels must still be the
    pixel-space value, because on square pixels those ARE the physical
    values — and `feret_max_calibrated` must still be the plain product,
    since with one scale there is nothing else it could be."""
    ds = _disc_image(1.0, 1.0)
    p = _particle(client, ds)
    assert p["feret_max_calibrated"] == pytest.approx(p["feret_max"] * 1.0, rel=1e-9)
    assert p["aspect_ratio"] == pytest.approx(1.0, abs=0.1)


def test_uncalibrated_image_still_reports_null_calibrated_lengths(client) -> None:
    """No calibration means no physical length — ADR 0004's absent rather
    than meaningless. The pixel-space fields stay present."""
    n = int(RADIUS_NM)
    img = np.zeros((2 * n + 24, 2 * n + 24), dtype=np.float64)
    rr, cc = draw.disk((n + 12, n + 12), n)
    img[rr, cc] = 100.0
    ds = DataStruct(data=img, kind=DataKind.IMAGE, axes=(AxisCal(), AxisCal()), metadata={})
    p = _particle(client, ds)
    assert p["feret_max_calibrated"] is None
    assert isinstance(p["feret_max"], float)
    assert isinstance(p["circularity"], float)


# ── grain-boundary network: two directions, two lengths ──────────────────


def test_boundary_network_weights_the_two_edge_directions_separately() -> None:
    """A grain boundary between two horizontally-adjacent pixels is a
    VERTICAL segment, whose physical length is the ROW extent — and vice
    versa. Summing the edge COUNT and multiplying by one scale assumes
    those are equal.

    Two grains split by a single straight vertical boundary make the
    arithmetic unambiguous: the boundary is `n_rows` vertical segments,
    each ROW_NM long, and contains no horizontal segments at all.
    """
    from fermiviewer.calc.grains import grain_stats

    rows, cols = 20, 30
    labels = np.zeros((rows, cols), np.int64)
    labels[:, : cols // 2] = 1
    labels[:, cols // 2 :] = 2
    raster = np.zeros((rows, cols), dtype=np.float64)

    stats = grain_stats(
        labels, raster, pixel_size=COL_NM, pixel_area=ROW_NM * COL_NM,
        spacing=(ROW_NM, COL_NM),
    )
    assert stats.boundary_network_px == pytest.approx(float(rows))
    assert stats.boundary_network_calibrated == pytest.approx(rows * ROW_NM)
    # the old single-scale form would have used the COLUMN scale here
    assert stats.boundary_network_calibrated != pytest.approx(rows * COL_NM)


def test_boundary_network_unchanged_on_square_pixels() -> None:
    """With equal scales the corrected form must collapse to exactly the
    product it replaced."""
    from fermiviewer.calc.grains import grain_stats

    rows, cols = 20, 30
    labels = np.zeros((rows, cols), np.int64)
    labels[:, : cols // 2] = 1
    labels[:, cols // 2 :] = 2
    raster = np.zeros((rows, cols), dtype=np.float64)
    for scale in (0.5, 1.0, 4.0):
        stats = grain_stats(
            labels, raster, pixel_size=scale, pixel_area=scale * scale,
            spacing=(scale, scale),
        )
        assert stats.boundary_network_calibrated == pytest.approx(
            stats.boundary_network_px * scale
        )
