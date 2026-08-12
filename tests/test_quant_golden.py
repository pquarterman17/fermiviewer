"""Quantification against the synthetic truth (SPECTRAL_WORKSPACE_PLAN #18).

`/eds/quantify`, `/eels/quantify` and `/eels/fit` are run on cubes whose
composition is known exactly, and their answers compared to the
`.truth.json` sidecar. `tools/make_synthetic_si.py` plants line and edge
intensities by INVERTING the application's own forward models — Cliff-Lorimer
weights for EDS, `eels_model.edge_shape_fn`'s differential cross-section for
EELS — so a perfect implementation would return the planted composition
exactly and every deviation below is a real property of the method.

Compared against `material_atomic_percent`, NOT `field_mean_atomic_percent`:
a quantifier measures the material and knows nothing about how much of the
field was vacuum, so comparing to the field mean is off by exactly the vacuum
fraction (6.25 % of eds-layers, 9.4 % of eels-layers).

What that scopes this to, honestly: the k-factors and cross-sections
themselves are NOT under test (planting and inverting with the same table
cannot check the table). What IS under test is everything between the cube
and the answer — window placement, background subtraction, per-pixel
normalisation, map assembly and the routes' own plumbing.

TOLERANCES THIS SUITE MEASURES (atomic percent, absolute, at the fixtures'
counts scale). Asserted as ceilings so a regression fails; NOT targets, and a
method that improves must tighten them:

  EDS, Cliff-Lorimer over integrated windows (`/eds/quantify`)
    eds-particles   max 2.2 pp; Al 36.20 vs 36.15, O 55.41 vs 55.93
    eds-layers      Al and O within 0.02 pp — but C 21.2 vs 10.0

    That light-element error is the flanking LINEAR background under a Kramers
    continuum. At C-Kalpha (0.277 keV) the continuum is steep and convex, so a
    straight line between the flanking windows sits well below the true
    background and the net comes back roughly double; the normalisation then
    deflates everything else (Si 38.0 vs 45.6). Switching the same
    quantification to the `bremsstrahlung` background makes it WORSE (measured:
    25.6 pp on eds-layers) — so this is not the endpoint hardcoding the wrong
    model. Model-based peak fitting is the answer for a light element on a
    steep continuum; window integration has this floor.

  EELS (`/eels/quantify` window integration, `/eels/fit` simultaneous model)
    eels-layers     both within 0.4 pp of the truth, on four stacked edges

    They agree with each other to 0.5 pp as well, which is the check that the
    cube is a real oracle rather than two methods failing the same way.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app
from fermiviewer.session import store

pytestmark = [pytest.mark.api, pytest.mark.eds]

ROOT = Path(__file__).resolve().parents[1]
SHAPE = (32, 24)
COUNTS = 40000.0


def _load_generator():
    """Import tools/make_synthetic_si.py — a script, not an installed module."""
    path = ROOT / "tools" / "make_synthetic_si.py"
    spec = importlib.util.spec_from_file_location("make_synthetic_si", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_synthetic_si"] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def cubes(tmp_path_factory) -> dict[str, tuple[Path, dict]]:
    """One cube per preset used here, built once (Poisson sampling a 32x24x2048
    cube is the slow part of this module)."""
    out = tmp_path_factory.mktemp("quant-golden")
    return {
        name: gen.build(gen.PRESETS[name], SHAPE, COUNTS, 0, out)
        for name in (
            "eds-particles", "eds-layers", "eels-layers",
            "eds-diffusion", "eds-thickness",
        )
    }


def _open(client: TestClient, path: Path) -> str:
    r = client.post("/api/session/open", json={"paths": [str(path)]})
    assert r.status_code == 200, r.text
    return r.json()[0]["id"]


def _decode_data16(resp) -> np.ndarray:
    """Reconstruct real values from `/image/{id}/data16`'s normalised uint16
    payload — the same X-Min/X-Max the WebGL render path decodes. 16-bit
    quantisation over the map's own range is far finer than the pp-level
    tolerances below, so this loses nothing the tests care about."""
    shape = tuple(int(n) for n in resp.headers["X-Shape"].split(","))
    vmin, vmax = float(resp.headers["X-Min"]), float(resp.headers["X-Max"])
    u16 = np.frombuffer(resp.content, dtype="<u2").reshape(shape)
    return vmin + (u16.astype(np.float64) / 65535.0) * (vmax - vmin)


def _errors(
    elements: list[str], percents: list[float], truth: dict
) -> dict[str, float]:
    """Signed at% error per element, so a test can name the element it means."""
    want = truth["material_atomic_percent"]
    return {
        sym: float(pct) - want[sym]
        for sym, pct in zip(elements, percents, strict=True)
    }


def _eds_quantify(client: TestClient, name: str, cubes) -> tuple[dict, dict]:
    path, truth = cubes[name]
    r = client.post(
        "/api/eds/quantify",
        json={"image_id": _open(client, path), "elements": truth["elements"]},
    )
    assert r.status_code == 200, r.text
    return r.json(), truth


def _eels_edges(truth: dict) -> list[dict]:
    """The windows the intensities were planted against — part of the ground
    truth, not a reader's choice: the planted edge area IS the cross-section
    integrated over exactly this window."""
    return [
        {
            "element": s["symbol"],
            "shell": s["shell"],
            "z": s["z"],
            "onset_ev": s["onset_ev"],
            "signal_window": s["signal_window"],
            "bg_window": s["bg_window"],
        }
        for s in truth["species"]
    ]


def _eels_post(client: TestClient, route: str, cubes) -> tuple[dict, dict]:
    path, truth = cubes["eels-layers"]
    r = client.post(
        route,
        json={
            "image_id": _open(client, path),
            "edges": _eels_edges(truth),
            "e0_kv": truth["beam_kv"],
            "beta_mrad": truth["beta_mrad"],
        },
    )
    assert r.status_code == 200, r.text
    return r.json(), truth


# -- EDS ---------------------------------------------------------------

def test_eds_recovers_the_synthetic_composition(client, cubes) -> None:
    """The headline: a cube of known composition quantifies back to it."""
    body, truth = _eds_quantify(client, "eds-particles", cubes)
    err = _errors(body["elements"], body["mean_atomic_pct"], truth)

    # Every element the generator planted comes back, none invented.
    assert set(body["elements"]) == set(truth["elements"])
    # The majors -- the numbers anyone would quote -- to better than 1 pp.
    assert abs(err["Al"]) < 1.0, err
    assert abs(err["O"]) < 1.0, err
    # And nothing is wrong by more than a couple of points.
    assert max(abs(v) for v in err.values()) < 3.0, err


def test_eds_recovers_the_majors_of_a_layer_stack_almost_exactly(client, cubes):
    """Al and O land within 0.02 pp on eds-layers -- worth pinning, because it
    is what makes the carbon error below attributable to carbon rather than to
    the pipeline being loose everywhere."""
    body, truth = _eds_quantify(client, "eds-layers", cubes)
    err = _errors(body["elements"], body["mean_atomic_pct"], truth)
    assert abs(err["Al"]) < 0.3, err
    assert abs(err["O"]) < 0.3, err


def test_eds_ranks_the_elements_correctly(client, cubes) -> None:
    """Weaker than the absolute check and much harder to satisfy by accident:
    a shared window, a mis-resolved line or a dropped k-factor all reorder the
    table even when the totals still sum to 100."""
    for name in ("eds-particles", "eds-layers"):
        body, truth = _eds_quantify(client, name, cubes)
        want = truth["material_atomic_percent"]
        got_order = [
            s for _, s in sorted(
                zip(body["mean_atomic_pct"], body["elements"], strict=True),
                reverse=True,
            )
        ]
        # C is excluded: its light-element bias is large enough to move it in
        # the ranking, which is the point of the next test.
        ranked = [s for s in got_order if s != "C"]
        expected = sorted(
            (s for s in body["elements"] if s != "C"),
            key=lambda s: want[s],
            reverse=True,
        )
        assert ranked == expected, (name, body["mean_atomic_pct"])


def test_eds_light_element_bias_is_bounded_and_documented(client, cubes) -> None:
    """C-Kalpha sits on the steep part of the Kramers continuum, where the
    flanking LINEAR background under-subtracts and the net comes back roughly
    double.

    Asserted as a ceiling, not a target. If a change improves this, the test
    fails and the module docstring's tolerance table must be tightened with
    it -- that is the intended way to find out that it got better.
    """
    body, truth = _eds_quantify(client, "eds-layers", cubes)
    err = _errors(body["elements"], body["mean_atomic_pct"], truth)
    assert err["C"] > 0, "the bias direction is over-reporting; re-derive if it flips"
    assert err["C"] < 13.0, err
    # Everything else is deflated by the normalisation that inflated C, so
    # their errors are that one error redistributed -- bounded, and all of one
    # sign, not independent.
    others = {k: v for k, v in err.items() if k != "C"}
    assert all(v < 0.3 for v in others.values()), others
    assert max(abs(v) for v in others.values()) < 9.0, others


def test_eds_reports_an_uncertainty_alongside_every_percentage(client, cubes) -> None:
    """A composition without an error bar cannot be compared to another one."""
    body, _ = _eds_quantify(client, "eds-particles", cubes)
    sigma = body["mean_atomic_pct_error"]
    assert len(sigma) == len(body["elements"])
    assert all(np.isfinite(s) and s >= 0 for s in sigma), sigma
    # Counting statistics at this many counts are small next to the method
    # bias above -- worth stating, so nobody reads sigma as total accuracy.
    assert max(sigma) < 5.0, sigma


# -- EELS --------------------------------------------------------------

def test_eels_window_integration_recovers_the_planted_edges(client, cubes) -> None:
    body, truth = _eels_post(client, "/api/eels/quantify", cubes)
    err = _errors(body["elements"], body["atomic_percent"], truth)

    assert set(body["elements"]) == set(truth["elements"])
    assert sum(body["atomic_percent"]) == pytest.approx(100.0, abs=1e-6)
    assert max(abs(v) for v in err.values()) < 1.0, err


def test_eels_model_fit_recovers_the_planted_edges(client, cubes) -> None:
    """The simultaneous multi-edge fit, on the same four stacked edges.

    This is what SPECTRAL #23 was opened for: the cube's edge shapes are now
    `eels_model`'s own differential cross-section, so the model has something
    to match. Before that they were a hand-rolled sawtooth and this route
    returned 50 pp -- evidence about the generator, not about the fit.
    """
    body, truth = _eels_post(client, "/api/eels/fit", cubes)
    assert body["success"] is True
    elements = [e["element"] for e in body["edges"]]
    percents = [e["atomic_percent"] for e in body["edges"]]
    err = _errors(elements, percents, truth)
    assert max(abs(v) for v in err.values()) < 1.0, err
    assert all(e["atomic_percent_error"] >= 0 for e in body["edges"])


def test_the_two_eels_methods_agree(client, cubes) -> None:
    """Independent inversions of the same cube -- one integrating windows over
    a per-edge power-law background, one fitting every edge and one background
    simultaneously. Agreement is the check that the cube is a real oracle
    rather than two methods failing the same way; it is also the claim that
    would break first if the planted edge shape drifted from the model."""
    window, _ = _eels_post(client, "/api/eels/quantify", cubes)
    model, _ = _eels_post(client, "/api/eels/fit", cubes)
    by_element = {e["element"]: e["atomic_percent"] for e in model["edges"]}
    for symbol, pct in zip(window["elements"], window["atomic_percent"], strict=True):
        assert by_element[symbol] == pytest.approx(pct, abs=1.0), (symbol, by_element)


def test_eels_windows_come_from_the_truth_sidecar(cubes) -> None:
    """The signal window is part of the ground truth, not a reader's choice:
    the planted intensity is the cross-section integrated over THAT window, so
    quantifying over a different one is answering a different question."""
    _, truth = cubes["eels-layers"]
    for s in truth["species"]:
        lo, hi = s["signal_window"]
        assert lo == pytest.approx(s["onset_ev"])
        assert hi - lo == pytest.approx(gen.EELS_SIGNAL_WIDTH_EV)
        bg_lo, bg_hi = s["bg_window"]
        assert bg_hi == pytest.approx(lo - gen.EELS_BG_GAP_EV)
        # The whole fit window must be ON the axis, or the background is
        # extrapolated from a truncated fit (it was: the preset used to start
        # at 80 eV, giving Si L23 19 eV of pre-edge and a 3 at% answer against
        # a truth of 46).
        assert bg_lo >= truth["energy_axis"]["range"][0]


# -- item 19: gradient + thickness-ramp presets -------------------------
#
# eds-thickness's tolerances below were MEASURED, not the item's a-priori
# guess. The plan that opened this item expected a Ni-O matrix to show a
# CL "deficit" for O; built and measured (2026-08-12), Ni's Z^4-scaled MAC
# for O's line is so large (this app's MAC formula has no absorption edges
# to cap it — see calc/eds.py's docstring) that z*a exceeds 100 within a
# few nm, which saturates plain Cliff-Lorimer to a near-single-element
# answer and defeats ZAF's iterative refinement (it starts from that
# saturated guess and cannot climb back out — verified directly against
# calc.eds.zaf_correction, not asserted from theory). Al2O3 keeps z*a in
# the 1-5x range across the 10-100 nm ramp this preset actually uses,
# where plain Cliff-Lorimer shows a real, growing bias and ZAF genuinely
# reduces it — and where the bias runs the OPPOSITE direction from the
# original guess: O is increasingly OVER-reported with thickness, not
# under-reported (Al carries the mirrored deficit). Both directions are
# real absorption stories; this is the one this app's own ZAF model
# actually produces for a reachable thin-film range.
#
#   eds-thickness (`/eds/quantify`, plain Cliff-Lorimer)
#     thick-end minus thin-end O at%: +21 pp (bounded 15-30 pp)
#   eds-thickness (`method="zaf"`, mid-column thickness)
#     max |at% error| over Al/O: <1 pp, vs plain CL's ~18 pp on the same cube

def test_eds_diffusion_recovers_the_profile(client, cubes) -> None:
    """`/eds/quantify` on eds-diffusion: the recovered Cu at% map, read back
    row by row, reproduces the truth's per-row profile at the pure ends and
    the middle, and falls monotonically across the graded zone."""
    path, truth = cubes["eds-diffusion"]
    body, _ = _eds_quantify(client, "eds-diffusion", cubes)
    maps = dict(zip(body["elements"], body["maps"], strict=True))
    cu = _decode_data16(client.get(f"/api/image/{maps['Cu']['id']}/data16"))

    prof = truth["profile"]["material_atomic_percent_per_row"]
    row_means = cu.mean(axis=1)
    n = len(prof["Cu"])
    mid = n // 2
    assert row_means[0] == pytest.approx(prof["Cu"][0], abs=2.0)
    assert row_means[mid] == pytest.approx(prof["Cu"][mid], abs=2.0)
    assert row_means[-1] == pytest.approx(prof["Cu"][-1], abs=2.0)
    graded_idx = [i for i, v in enumerate(prof["Cu"]) if 1.0 < v < 99.0]
    graded_rows = row_means[graded_idx]
    assert np.all(np.diff(graded_rows) <= 0.5), (
        "Cu must fall monotonically across the gradient zone"
    )
    # The gradient runs along y only: a row-mean check alone cannot tell a
    # correct row-wise gradient from one that varies along x instead (row
    # means would still land near truth by coincidence — measured). Pin
    # spatial uniformity ACROSS one graded row directly.
    within_row_spread = cu[graded_idx[len(graded_idx) // 2], :].std()
    assert within_row_spread < 3.0, within_row_spread


def test_composition_profile_route_recovers_a_straight_line(client, cubes) -> None:
    """`/analyze/composition-profile` along the gradient axis, over the
    registered at% maps, reproduces the endpoints and stays close to the
    straight line joining them — the deliverable the gradient preset exists
    to test.

    Swept over just the graded zone, not the whole field: the field also
    contains the two PURE flanking phases, which flatten the swept profile
    into a plateau-ramp-plateau shape no straight line fits — that shape is
    real (`test_eds_diffusion_recovers_the_profile` covers the plateaus),
    it just is not what this test is checking.
    """
    path, truth = cubes["eds-diffusion"]
    img_id = _open(client, path)
    r = client.post(
        "/api/eds/quantify",
        json={"image_id": img_id, "elements": truth["elements"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    maps = dict(zip(body["elements"], body["maps"], strict=True))
    w = truth["shape"][1]
    prof = truth["profile"]["material_atomic_percent_per_row"]["Cu"]
    graded_idx = [i for i, v in enumerate(prof) if 1.0 < v < 99.0]
    y1, y2 = graded_idx[0] + 1, graded_idx[-1] + 1   # 1-based rows

    r2 = client.post(
        "/api/analyze/composition-profile",
        json={
            "image_id": img_id,
            "map_ids": [maps["Cu"]["id"], maps["Ni"]["id"]],
            "elements": ["Cu", "Ni"],
            "x1": w // 2, "y1": y1, "x2": w // 2, "y2": y2,
            "n_points": len(graded_idx),
        },
    )
    assert r2.status_code == 200, r2.text
    pbody = r2.json()
    cu_profile = np.array(pbody["atomic_pct"][pbody["elements"].index("Cu")])
    truth_cu = [prof[i] for i in graded_idx]
    assert cu_profile[0] == pytest.approx(truth_cu[0], abs=2.0)
    assert cu_profile[-1] == pytest.approx(truth_cu[-1], abs=2.0)
    line = np.linspace(cu_profile[0], cu_profile[-1], len(cu_profile))
    assert np.max(np.abs(cu_profile - line)) < 3.0


def test_thickness_cl_bias_is_real_and_bounded(client, cubes) -> None:
    """Plain Cliff-Lorimer on eds-thickness: O at% grows with thickness.

    Asserted as a floor AND a ceiling, not a target — see the tolerance
    table above this section for the measured direction and why it runs
    opposite the item's original guess.
    """
    path, truth = cubes["eds-thickness"]
    body, _ = _eds_quantify(client, "eds-thickness", cubes)
    maps = dict(zip(body["elements"], body["maps"], strict=True))
    o = _decode_data16(client.get(f"/api/image/{maps['O']['id']}/data16"))
    col_means = o.mean(axis=0)
    bias = col_means[-1] - col_means[0]
    assert bias > 15.0, bias
    assert bias < 30.0, bias


def test_thickness_zaf_beats_cl(client, cubes) -> None:
    """`method="zaf"`, given the true mid-column thickness, recovers
    eds-thickness far better than plain Cliff-Lorimer over the SAME cube —
    the ramp cube exercising `zaf_correction`'s correction machinery, not
    just its no-op zero-thickness limit."""
    path, truth = cubes["eds-thickness"]
    cl_body, _ = _eds_quantify(client, "eds-thickness", cubes)
    cl_err = _errors(cl_body["elements"], cl_body["mean_atomic_pct"], truth)

    t = truth["thickness"]
    mid_nm = t["nm_per_column"][len(t["nm_per_column"]) // 2]
    r = client.post(
        "/api/eds/quantify",
        json={
            "image_id": _open(client, path),
            "elements": truth["elements"],
            "method": "zaf",
            "thickness_nm": mid_nm,
            "take_off_angle_deg": t["take_off_angle_deg"],
        },
    )
    assert r.status_code == 200, r.text
    zaf_body = r.json()
    zaf_err = _errors(zaf_body["elements"], zaf_body["mean_atomic_pct"], truth)

    cl_max = max(abs(v) for v in cl_err.values())
    zaf_max = max(abs(v) for v in zaf_err.values())
    assert zaf_max < cl_max, (zaf_err, cl_err)
    assert zaf_max < 1.0, zaf_err


# -- the generator's own invariants ------------------------------------

def test_cube_never_wraps_uint16(cubes) -> None:
    """`astype(np.uint16)` wraps silently, and a wrapped peak looks exactly
    like a dark pixel in a noisy map. The rescale that prevents it is a global
    factor, so it cannot change any ratio quantification reads."""
    for name, (_, truth) in cubes.items():
        applied = truth["counts_scale_applied"]
        assert 0 < applied <= truth["counts_scale"], name


def test_the_material_truth_is_the_field_truth_without_the_vacuum(cubes) -> None:
    """Two truths, and using the wrong one is a silent error of exactly the
    empty fraction. `material_atomic_percent` sums to 100 and is what a
    quantifier reports; `field_mean_atomic_percent` averages over the whole
    raster, vacuum included."""
    for name, (_, truth) in cubes.items():
        material = truth["material_atomic_percent"]
        field = truth["field_mean_atomic_percent"]
        assert sum(material.values()) == pytest.approx(100.0, abs=0.02), name
        assert material.keys() == field.keys(), name
        # Same composition, one scale factor apart.
        ratios = [material[k] / field[k] for k in material if field[k] > 0]
        assert max(ratios) == pytest.approx(min(ratios), rel=1e-3), name
