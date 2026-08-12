"""Quantification against the synthetic truth (SPECTRAL_WORKSPACE_PLAN #18).

`/eds/quantify` and `/eels/quantify` are run on cubes whose composition is
known exactly, and their answers compared to the `.truth.json` sidecar. The
cubes are built by `tools/make_synthetic_si.py`, which plants line and edge
intensities by INVERTING the application's own forward models — Cliff-Lorimer
weights for EDS, partial ionization cross-sections for EELS — so a perfect
implementation would return the planted composition exactly and every
deviation below is a real property of the method.

What that scopes this to, honestly: the k-factors and cross-sections
themselves are NOT under test here (planting and inverting with the same
table cannot check the table). What IS under test is everything between the
cube and the answer — window placement, background subtraction, per-pixel
normalisation, map assembly and the route's own plumbing — which is where
these pipelines actually break.

TOLERANCES THIS SUITE MEASURES (atomic percent, absolute, at the fixtures'
counts scale). They are asserted as ceilings so a regression fails; they are
NOT targets, and a method that improves must tighten them:

  EDS, Cliff-Lorimer over integrated windows
    eds-particles   Al 36.2 vs 36.1, O 55.4 vs 55.9  → majors within 0.6 pp
                    C   5.8 vs  3.6, Ta 2.6 vs  4.3  → minors within 2.2 pp
    eds-layers      C  21.2 vs  9.4                  → 11.8 pp, see below

    The light-element bias is the flanking LINEAR background under a Kramers
    continuum. At C-Kα (0.277 keV) the continuum is steep and convex, so a
    straight line between the flanking windows sits well below the true
    background and the net comes back roughly double. Switching the same
    quantification to the `bremsstrahlung` background makes it WORSE (25.6 pp
    on eds-layers, 21.5 on eds-particles) — measured, not assumed — so this is
    not a matter of the endpoint hardcoding the wrong model. Model-based peak
    fitting (`/eds/peakfit`) is the answer for light elements on a steep
    continuum; window integration has this floor.

  EELS, power-law pre-edge fit per edge (`/eels/quantify`)
    eels-layers     four stacked edges → up to 26 pp; O, the edge with no
                    other onset above it, within 0.2 pp

    Every edge sits on the tails of the edges below it, and a sum of power
    laws with different exponents is not a power law, so a single pre-edge fit
    cannot remove them exactly. The residue inflates the upper edges and (by
    the normalisation) deflates the lower ones — the known reason real EELS
    quantification strips edges sequentially rather than window-integrating
    them independently.

    NOT asserted here: the model-based `/eels/fit`, which fits one background
    plus every edge simultaneously and is the method that should beat the
    above. It returns 50 pp on this cube, because the generator's edge SHAPE
    is a hand-rolled sawtooth-plus-white-lines rather than the application's
    own differential cross-section — so the model has nothing to match. That
    is a gap in the GENERATOR, not evidence about the fit: the same rule that
    already makes it take line positions from `calc.eds.line_energy` should
    make it take edge shapes from `calc.eels_model`. Booked in the plan; until
    then this cube cannot be an oracle for the model fit.
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
    """One cube per preset used here, built once (Poisson sampling a 32×24×2048
    cube is the slow part of this module)."""
    out = tmp_path_factory.mktemp("quant-golden")
    return {
        name: gen.build(gen.PRESETS[name], SHAPE, COUNTS, 0, out)
        for name in ("eds-particles", "eds-layers", "eels-layers")
    }


def _open(client: TestClient, path: Path) -> str:
    r = client.post("/api/session/open", json={"paths": [str(path)]})
    assert r.status_code == 200, r.text
    return r.json()[0]["id"]


def _eds_quantify(client: TestClient, name: str, cubes) -> tuple[dict, dict]:
    path, truth = cubes[name]
    r = client.post(
        "/api/eds/quantify",
        json={"image_id": _open(client, path), "elements": truth["elements"]},
    )
    assert r.status_code == 200, r.text
    return r.json(), truth


def _errors(body: dict, truth: dict, key: str, got_key: str) -> dict[str, float]:
    """Signed at% error per element, so a test can name the element it means."""
    want = truth["field_mean_atomic_percent"]
    return {
        sym: float(pct) - want[sym]
        for sym, pct in zip(body[key], body[got_key], strict=True)
    }


# ── EDS ───────────────────────────────────────────────────────────────

def test_eds_recovers_the_synthetic_composition(client, cubes) -> None:
    """The headline: a cube of known composition quantifies back to it."""
    body, truth = _eds_quantify(client, "eds-particles", cubes)
    err = _errors(body, truth, "elements", "mean_atomic_pct")

    # Every element the generator planted comes back, none invented.
    assert set(body["elements"]) == set(truth["elements"])
    # The majors — the numbers anyone would quote — to better than 1 pp.
    assert abs(err["Al"]) < 1.0, err
    assert abs(err["O"]) < 1.0, err
    # And nothing is wrong by more than a couple of points.
    assert max(abs(v) for v in err.values()) < 3.0, err


def test_eds_ranks_the_elements_correctly(client, cubes) -> None:
    """Weaker than the absolute check and much harder to satisfy by accident:
    a shared window, a mis-resolved line or a dropped k-factor all reorder the
    table even when the totals still sum to 100."""
    for name in ("eds-particles", "eds-layers"):
        body, truth = _eds_quantify(client, name, cubes)
        want = truth["field_mean_atomic_percent"]
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
    """C-Kα sits on the steep part of the Kramers continuum, where the flanking
    LINEAR background under-subtracts and the net comes back roughly double.

    Asserted as a ceiling, not a target. If a change improves this, the test
    fails and the module docstring's tolerance table must be tightened with
    it — that is the intended way to find out that it got better.
    """
    body, truth = _eds_quantify(client, "eds-layers", cubes)
    err = _errors(body, truth, "elements", "mean_atomic_pct")
    assert err["C"] > 0, "the bias direction is over-reporting; re-derive if it flips"
    assert err["C"] < 14.0, err
    # Everything that is not the light element stays close.
    others = {k: v for k, v in err.items() if k != "C"}
    assert max(abs(v) for v in others.values()) < 6.0, others


def test_eds_reports_an_uncertainty_alongside_every_percentage(client, cubes) -> None:
    """A composition without an error bar cannot be compared to another one."""
    body, _ = _eds_quantify(client, "eds-particles", cubes)
    sigma = body["mean_atomic_pct_error"]
    assert len(sigma) == len(body["elements"])
    assert all(np.isfinite(s) and s >= 0 for s in sigma), sigma
    # Counting statistics at this many counts are small next to the method
    # bias above — worth stating, so nobody reads sigma as total accuracy.
    assert max(sigma) < 5.0, sigma


# ── EELS ──────────────────────────────────────────────────────────────

def test_eels_recovers_the_planted_edges(client, cubes) -> None:
    path, truth = cubes["eels-layers"]
    r = client.post(
        "/api/eels/quantify",
        json={
            "image_id": _open(client, path),
            "edges": [
                {
                    "element": s["symbol"],
                    "shell": s["shell"],
                    "z": s["z"],
                    "onset_ev": s["onset_ev"],
                    "signal_window": s["signal_window"],
                    "bg_window": s["bg_window"],
                }
                for s in truth["species"]
            ],
            "e0_kv": truth["beam_kv"],
            "beta_mrad": truth["beta_mrad"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    err = _errors(body, truth, "elements", "atomic_percent")

    assert set(body["elements"]) == set(truth["elements"])
    assert sum(body["atomic_percent"]) == pytest.approx(100.0, abs=1e-6)
    # Every edge is detected as present — none collapses to zero, which is
    # what a mis-placed window or a runaway background fit produces.
    assert all(pct > 1.0 for pct in body["atomic_percent"]), body["atomic_percent"]
    # The stacked-edge ceiling from the docstring. A ceiling, not a target.
    assert max(abs(v) for v in err.values()) < 30.0, err
    # O sits above every other edge's onset and is the one the pre-edge fit
    # handles cleanly; it is the tightest claim this cube supports.
    assert abs(err["O"]) < 3.0, err


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


# ── the generator's own invariants ────────────────────────────────────

def test_cube_never_wraps_uint16(cubes) -> None:
    """`astype(np.uint16)` wraps silently, and a wrapped peak looks exactly
    like a dark pixel in a noisy map. The rescale that prevents it is a global
    factor, so it cannot change any ratio quantification reads."""
    for name, (_, truth) in cubes.items():
        applied = truth["counts_scale_applied"]
        assert 0 < applied <= truth["counts_scale"], name

