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
