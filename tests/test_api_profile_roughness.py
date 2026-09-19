"""Interfacial roughness from the box, not from the averaged profile.

The claim under test: an edge width measured on the laterally averaged
profile cannot tell a ROUGH interface from a GRADED one, because both widen
it the same way (``sigma_erf² ~ sigma_chem² + sigma_w²``). Tracing the
interface column by column measures the roughness directly.

So every test here is built on a stack where the two are planted
SEPARATELY — a chosen intrinsic grading, and a chosen sinusoidal waviness —
and checks that the endpoint recovers each. A test on a single specimen
could not distinguish a working decomposition from a constant.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.ndimage import gaussian_filter1d
from scipy.special import erf

from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.imaging]

H, W = 160, 120
PX = 1.0
CENTRE = 80.0


def _roughness(rms: float, seed: int, correlation: float = 6.0) -> np.ndarray:
    """A per-column height offset with a known rms and a finite correlation
    length — smoothed white noise, rescaled.

    Deliberately NOT a sine. `trace_roughness.robust_sigma` is MAD-based and
    Gaussian-calibrated (MAD/0.6745), which is right for real roughness but
    reads a pure sinusoid about 1.48x high — the median absolute deviation
    of a sine is 0.707A where a Gaussian of the same rms gives 0.6745σ. A
    sine would make this test measure the estimator's calibration rather
    than the pipeline.
    """
    if rms == 0.0:
        return np.zeros(W)
    rng = np.random.default_rng(seed)
    raw = gaussian_filter1d(rng.normal(size=W), correlation, mode="wrap")
    return rms * raw / raw.std()


def _stack(grading: float, waviness: float, seed: int = 5) -> np.ndarray:
    """One interface with a known intrinsic width and a known rms waviness.

    Each column is an erf of width `grading` centred on
    ``CENTRE + offset(column)``. Built analytically so the image carries no
    interpolation blur of its own — any extra width the pipeline reports is
    the pipeline's.
    """
    r, c = np.mgrid[0:H, 0:W].astype(np.float64)
    offset = _roughness(waviness, seed)[c.astype(int)]
    return 0.5 * (1 + erf((r - (CENTRE + offset)) / (grading * np.sqrt(2))))


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _image(client: TestClient, tmp_path, img: np.ndarray, name: str) -> str:
    f = write_mini_dm4(
        tmp_path / name, dims=[W, H],
        data=img.ravel().astype(np.float32), data_type=2,
        cal=[
            {"scale": PX, "origin": 0, "units": "nm"},
            {"scale": PX, "origin": 0, "units": "nm"},
        ],
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


def _measure(client: TestClient, image_id: str, **kw) -> dict:
    body = {
        "image_id": image_id,
        # a vertical line down the middle: across the horizontal interface
        "a": [1, 60], "b": [H, 60],
        "width": 100.0,
        **kw,
    }
    r = client.post("/api/measure/profile-roughness", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_wavy_interface_reports_the_waviness_that_was_planted(
    client, tmp_path
) -> None:
    rms = 4.0
    out = _measure(client, _image(client, tmp_path, _stack(1.5, rms), "wavy.dm4"))
    assert out["sigma_w"] == pytest.approx(rms, rel=0.30)
    assert out["unit"] == "nm"
    assert out["lateral_samples"] == 100


def test_a_flat_interface_reports_almost_no_waviness(client, tmp_path) -> None:
    """The negative control: the same pipeline on a flat interface must NOT
    return the roughness of the wavy one."""
    out = _measure(client, _image(client, tmp_path, _stack(1.5, 0.0), "flat.dm4"))
    assert out["sigma_w"] < 0.5


def test_the_averaged_width_cannot_separate_grading_from_roughness(
    client, tmp_path
) -> None:
    """The reason this endpoint exists.

    A sharp-but-wavy interface and a smooth-but-graded one are built to have
    nearly the SAME averaged edge width. Anything reading only that width
    calls them identical; sigma_w tells them apart.
    """
    wavy = _measure(client, _image(client, tmp_path, _stack(1.0, 4.0), "a.dm4"))
    graded = _measure(client, _image(client, tmp_path, _stack(4.1, 0.0), "b.dm4"))
    # same story from the averaged profile ...
    assert wavy["sigma_erf"] == pytest.approx(graded["sigma_erf"], rel=0.25)
    # ... and completely different once the columns are traced
    assert wavy["sigma_w"] > 8 * graded["sigma_w"]


def test_the_decomposition_recovers_the_grading_that_was_planted(
    client, tmp_path
) -> None:
    grading = 4.0
    out = _measure(client, _image(client, tmp_path, _stack(grading, 4.0), "mix.dm4"))
    assert out["sigma_chem"] == pytest.approx(grading, rel=0.35)
    # and it is below the averaged width it was subtracted out of
    assert out["sigma_chem"] < out["sigma_erf"]


def test_a_roughness_limited_interface_reports_no_grading_rather_than_zero(
    client, tmp_path
) -> None:
    """When the waviness accounts for the whole averaged width there is no
    resolvable grading left. That is an absent answer, not a zero one."""
    out = _measure(
        client,
        _image(client, tmp_path, _stack(0.6, 12.0), "rough.dm4"),
        trace_window=40,
    )
    assert out["sigma_chem"] is None


def test_a_trace_clipped_by_its_window_says_so_instead_of_under_reporting(
    client, tmp_path
) -> None:
    """The defect this guard exists for.

    `trace_interface` only looks +/-window around the interface, so an
    interface that wanders further is clipped: the trace flattens against
    the bound. On this stack (true rms 12 px) the default window of 10
    returns sigma_w near 3.9 — a threefold underestimate — while
    `quality` still reads 1.00, because every column WAS traced, just to
    the wrong place. Nothing in the answer said so before.
    """
    img = _image(client, tmp_path, _stack(0.6, 12.0), "clip.dm4")
    narrow = _measure(client, img, trace_window=10)
    wide = _measure(client, img, trace_window=40)

    assert narrow["quality"] == pytest.approx(1.0)   # the metric that misleads
    # about half the columns are pinned here; the threshold is set well
    # above the 5% the warning fires at and far from the wide case's 0
    assert narrow["window_limited_fraction"] > 0.25
    assert narrow["sigma_w"] < 0.5 * wide["sigma_w"]
    assert any("LOWER BOUND" in line for line in narrow["limitations"])

    # a window big enough to hold the interface is neither clipped nor warned
    assert wide["window_limited_fraction"] == pytest.approx(0.0)
    assert not any("LOWER BOUND" in line for line in wide["limitations"])


def test_a_box_one_column_wide_is_refused(client, tmp_path) -> None:
    """Roughness is measured ACROSS the box. A single-column box is a line,
    and a line has nothing to compare against itself."""
    img = _image(client, tmp_path, _stack(1.5, 4.0), "thin.dm4")
    r = client.post(
        "/api/measure/profile-roughness",
        json={"image_id": img, "a": [1, 60], "b": [H, 60], "width": 3.0},
    )
    # width 3 is the documented floor and must work ...
    assert r.status_code == 200
    # ... while pydantic refuses anything below it
    r2 = client.post(
        "/api/measure/profile-roughness",
        json={"image_id": img, "a": [1, 60], "b": [H, 60], "width": 1.0},
    )
    assert r2.status_code == 422


def test_an_interface_position_outside_the_box_is_refused(client, tmp_path) -> None:
    img = _image(client, tmp_path, _stack(1.5, 4.0), "oob.dm4")
    r = client.post(
        "/api/measure/profile-roughness",
        json={
            "image_id": img, "a": [1, 60], "b": [H, 60],
            "width": 60.0, "interface_pos": 5000.0,
        },
    )
    assert r.status_code == 422
    assert "outside the box" in r.json()["detail"]


def test_the_op_and_the_route_measure_the_same_box(client, tmp_path) -> None:
    """A recipe step and the interactive call must not disagree about one
    specimen. The op takes the line as four scalars rather than a region
    reference so it replays on a machine with no project (ADR 0007 §11)."""
    from fermiviewer.ops import run
    from fermiviewer.session import store as session_store

    img = _image(client, tmp_path, _stack(1.5, 4.0), "op.dm4")
    route = _measure(client, img, trace_window=20)
    result = run(
        "profile_roughness",
        session_store.get(img),
        {
            "row1": 1.0, "col1": 60.0, "row2": float(H), "col2": 60.0,
            "width": 100.0, "interface_pos": -1.0, "trace_window": 20.0,
        },
    )
    scalars = {
        o["name"]: o["data"]["value"]
        for o in result.value["outputs"]
        if o["kind"] == "scalar"
    }
    assert scalars["sigma_w"] == pytest.approx(route["sigma_w"], rel=1e-9)
    assert scalars["sigma_erf"] == pytest.approx(route["sigma_erf"], rel=1e-9)
    assert result.value["lateral_samples"] == route["lateral_samples"]
