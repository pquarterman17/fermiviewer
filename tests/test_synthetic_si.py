"""The synthetic SI generator must produce cubes the real pipeline reads.

A test-data generator that drifts from the loader is worse than none: it makes
GUI work look verified against data the app never actually parsed that way.
These tests run the generator end to end — write a real ``.hspy``, load it with
the production reader, and check the element maps land where the ground truth
says the material is.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from fermiviewer.calc.eds_maps import element_map
from fermiviewer.datastruct import DataKind
from fermiviewer.io.hspy import load_hspy

ROOT = Path(__file__).resolve().parents[1]


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


@pytest.fixture(scope="module")
def eds_cube(tmp_path_factory) -> tuple[Path, dict]:
    out = tmp_path_factory.mktemp("synthetic")
    return gen.build(gen.PRESETS["eds-layers"], (24, 16), 4000.0, 0, out)


def test_eds_cube_loads_as_a_spectrum_image(eds_cube) -> None:
    path, truth = eds_cube
    ds = load_hspy(path)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (24, 16, truth["shape"][2])
    # the energy axis must survive the round trip, or every window is wrong
    energy = ds.axes[2].axis(ds.data.shape[2])
    assert ds.axes[2].units == "keV"
    assert energy[0] == pytest.approx(truth["energy_axis"]["offset"])
    assert energy[1] - energy[0] == pytest.approx(truth["energy_axis"]["scale"])


def test_declared_elements_reach_the_picker(eds_cube) -> None:
    """The EDS element picker highlights meta['elements']; without it a
    synthetic cube arrives looking like it contains nothing."""
    path, truth = eds_cube
    ds = load_hspy(path)
    assert ds.metadata["elements"] == truth["elements"]
    assert set(truth["elements"]) == {"Al", "C", "O", "Si", "Ta"}


def test_element_maps_localize_where_the_truth_says(eds_cube) -> None:
    path, truth = eds_cube
    ds = load_hspy(path)
    energy = ds.axes[2].axis(ds.data.shape[2])
    rows = ds.data.shape[0]
    by_symbol = {s["symbol"]: s for s in truth["species"]}

    def row_profile(symbol: str) -> np.ndarray:
        line = by_symbol[symbol]["energy_kev"]
        half = by_symbol[symbol]["fwhm_kev"]
        m = element_map(ds.data, energy, line - half, line + half, bg="linear")
        return np.asarray(m).mean(axis=1)

    # C caps the stack (rows 6–16% of the field), Si is the substrate (62–100%)
    carbon = row_profile("C")
    silicon = row_profile("Si")
    assert carbon.argmax() < rows * 0.25, "C should peak in the cap, near the top"
    assert silicon.argmax() > rows * 0.60, "Si should peak in the substrate"
    # and each should be strongly localized, not smeared across the field
    assert carbon[: int(rows * 0.25)].mean() > 3 * carbon[int(rows * 0.62) :].mean()
    assert silicon[int(rows * 0.62) :].mean() > 3 * silicon[: int(rows * 0.25)].mean()


def test_vacuum_rows_carry_no_signal(eds_cube) -> None:
    """The top 6% is vacuum: no peaks and no continuum. A generator that
    leaked background into vacuum would make every background model look
    better than it is."""
    path, _ = eds_cube
    ds = load_hspy(path)
    assert ds.data[0].sum() == 0


def test_truth_sidecar_is_written_and_consistent(eds_cube) -> None:
    path, truth = eds_cube
    on_disk = json.loads(path.with_suffix(".truth.json").read_text())
    assert on_disk == truth
    total = sum(truth["field_mean_atomic_percent"].values())
    # 6% of the field is vacuum, so the field-mean fractions sum to ~94%
    assert 90.0 < total < 100.0


def test_eels_preset_includes_its_lowest_edge(tmp_path) -> None:
    """Si L23 sits at 99 eV; an axis starting above it silently drops Si while
    the phase list still claims it is there."""
    path, truth = gen.build(gen.PRESETS["eels-layers"], (16, 12), 4000.0, 0, tmp_path)
    ds = load_hspy(path)
    assert ds.axes[2].units == "eV"
    symbols = {s["symbol"] for s in truth["species"]}
    assert symbols == {"C", "O", "Si", "Ti"}
    onsets = {s["symbol"]: s["onset_ev"] for s in truth["species"]}
    energy = ds.axes[2].axis(ds.data.shape[2])
    assert energy[0] < min(onsets.values())


def _open_and_identify(client, path: Path) -> tuple[dict, set[str]]:
    opened = client.post("/api/session/open", json={"paths": [str(path)]})
    assert opened.status_code == 200, opened.text
    payload = opened.json()
    meta = payload[0] if isinstance(payload, list) else payload
    auto = client.post("/api/eds/auto-assign", json={"image_id": meta["id"]})
    assert auto.status_code == 200, auto.text
    found = {
        a["candidates"][0]["symbol"]
        for a in auto.json()["assignments"]
        if a["candidates"]
    }
    return meta, found


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from fermiviewer.server import create_app
    from fermiviewer.session import store

    store.clear()
    yield TestClient(create_app(), base_url="http://127.0.0.1")
    store.clear()


def test_declared_elements_survive_the_api(client, tmp_path) -> None:
    """`meta['elements']` is a list, and the ImageMeta filter used to drop
    every non-scalar — so the EDS picker never received the acquisition's
    declared elements from any parser."""
    path, truth = gen.build(gen.PRESETS["eds-layers"], (20, 16), 4000.0, 0, tmp_path)
    meta, _ = _open_and_identify(client, path)
    assert meta["meta"]["elements"] == truth["elements"]


def test_auto_id_recovers_the_planted_elements(client, tmp_path) -> None:
    """End to end: what the generator planted is what auto-ID reports."""
    path, truth = gen.build(gen.PRESETS["eds-layers"], (24, 20), 4000.0, 0, tmp_path)
    _, found = _open_and_identify(client, path)
    planted = set(truth["elements"])
    assert found == planted, f"missed {planted - found}, spurious {found - planted}"


def test_auto_id_cannot_separate_the_overlap_preset(client, tmp_path) -> None:
    """Ta M is buried under Si K, so no peak finder can resolve it. That is
    the point of the preset: it is the case where the user must add the
    element by hand, and a regression here would mean the overlap stopped
    being an overlap."""
    path, truth = gen.build(gen.PRESETS["eds-overlap"], (24, 20), 4000.0, 0, tmp_path)
    _, found = _open_and_identify(client, path)
    planted = set(truth["elements"])
    assert "Ta" not in found
    assert planted - found == {"Ta"}, "only Ta should be unresolvable"


def test_overlap_preset_really_overlaps() -> None:
    """The eds-overlap preset is only useful if the app's own line selection
    puts Ta on M next to Si K — assert the physics, not the intent."""
    from fermiviewer.calc.eds import line_energy

    kv = gen.PRESETS["eds-overlap"].beam_kv
    ta, ta_line = line_energy("Ta", beam_kv=kv)
    si, si_line = line_energy("Si", beam_kv=kv)
    assert (ta_line, si_line) == ("M", "K")
    separation = abs(si - ta)
    assert separation < gen.detector_fwhm_kev(si), (
        f"Ta {ta_line} and Si {si_line} are {separation:.3f} keV apart, which is "
        "wider than the detector resolution — no longer an interference case"
    )


# ── item 19: gradient + thickness-ramp presets ─────────────────────────

def test_existing_presets_unchanged(tmp_path) -> None:
    """Gradient/ThicknessRamp support landed in the SAME `_fraction_maps` /
    `_eds_cube` / `build` functions the four original presets already run
    through. `total_counts` folds in every per-pixel intensity the Poisson
    draw touched, so a leaked default (a ref_nm scale applied
    unconditionally, a za map defaulting to something other than 1) would
    move it — pinned against the pre-item-19 value."""
    path, truth = gen.build(gen.PRESETS["eds-layers"], (24, 16), 4000.0, 0, tmp_path)
    assert "profile" not in truth
    assert "thickness" not in truth
    assert truth["total_counts"] == 63889136


def test_gradient_endpoints_and_midpoint(tmp_path) -> None:
    """eds-diffusion's Cu -> Ni gradient: the truth's per-row profile starts
    at pure Cu, ends at pure Ni, and crosses ~50/50 near the middle of the
    graded zone — AND actually varies across that zone rather than sitting
    at a constant 50/50 throughout, which is what a lerp using `t` for both
    ends produces (near and far cancel identically at every row, not just
    the midpoint — the endpoint/midpoint checks alone cannot tell that
    apart from a correct lerp, since both interpretations agree there)."""
    _, truth = gen.build(gen.PRESETS["eds-diffusion"], (32, 24), 4000.0, 0, tmp_path)
    prof = truth["profile"]["material_atomic_percent_per_row"]
    assert prof["Cu"][0] == pytest.approx(100.0, abs=0.5)
    assert prof["Ni"][0] == pytest.approx(0.0, abs=0.5)
    assert prof["Cu"][-1] == pytest.approx(0.0, abs=0.5)
    assert prof["Ni"][-1] == pytest.approx(100.0, abs=0.5)
    mid = len(prof["Cu"]) // 2
    assert prof["Cu"][mid] == pytest.approx(50.0, abs=5.0)
    graded = [v for v in prof["Cu"] if 1.0 < v < 99.0]
    assert len(graded) > 5, "the graded zone should span several rows"
    assert max(graded) - min(graded) > 50.0, (
        "the graded zone must vary, not sit flat at one composition"
    )


def test_gradient_rows_sum_to_material(tmp_path) -> None:
    """Every row of `material_atomic_percent_per_row` sums to 100, and the
    row AVERAGE reproduces the scalar `material_atomic_percent` — the two
    truths must never disagree, the same guarantee
    `test_the_material_truth_is_the_field_truth_without_the_vacuum` makes in
    test_quant_golden.py for the field/material split."""
    _, truth = gen.build(gen.PRESETS["eds-diffusion"], (32, 24), 4000.0, 0, tmp_path)
    prof = truth["profile"]["material_atomic_percent_per_row"]
    n = len(prof["Cu"])
    for i in range(n):
        total = sum(prof[s][i] for s in prof)
        assert total == pytest.approx(100.0, abs=0.02), i
    for symbol, scalar in truth["material_atomic_percent"].items():
        row_avg = sum(prof[symbol]) / n
        assert row_avg == pytest.approx(scalar, abs=0.1)


def test_thickness_ramp_scales_intensity_not_composition(tmp_path) -> None:
    """eds-thickness's ramp must move total signal, not each pixel's element
    balance on its own — a PURE intensity scale would cancel identically in
    Cliff-Lorimer's per-pixel normalisation (the algebraic reason item 19
    rejected a pure ramp and plants absorption instead; see the module
    docstring). The observed thick/thin ratio EXCEEDS the pure geometric
    ramp ratio because the planted z*a absorption factor also grows with
    thickness, on top of — not instead of — the t/ref scale.

    Measured at the golden fixture's shape/counts/seed (deterministic:
    fixed seed, no tolerance needed beyond the bound itself)."""
    path, truth = gen.build(gen.PRESETS["eds-thickness"], (32, 24), 40000.0, 0, tmp_path)
    ds = load_hspy(path)
    col_totals = ds.data.sum(axis=(0, 2)).astype(np.float64)
    assert np.all(np.diff(col_totals) > 0), "thicker columns must carry more signal"
    nm = truth["thickness"]["nm_per_column"]
    ramp_ratio = nm[-1] / nm[0]
    observed_ratio = col_totals[-1] / col_totals[0]
    # Comfortably above the PURE geometric ratio (measured 1.54x it) so a
    # dropped za contribution — which leaves observed_ratio barely above
    # ramp_ratio, ~1.001x it — fails this bound instead of slipping through.
    assert observed_ratio > 1.2 * ramp_ratio
    assert observed_ratio < 3 * ramp_ratio
