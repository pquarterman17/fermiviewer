"""Smoke tests for examples/ (Scripting #3): keeps the scripted-workflow
docs honest by actually running them, not just eyeballing the source.

Examples 1 and 2 need no external data and run on every ``pytest`` pass —
tiny synthetic arrays, well under a second each. Example 3 needs the same
local-only real-instrument corpus every other ``realdata``-marked test in
this repo needs, and skips exactly the same way when it's absent (see
``fermiviewer.devsamples`` / ``tests/conftest.py``).
"""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


def _run_example(name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Execute an example script with cwd = tmp_path, so its
    ``./fv_example_output/`` lands there instead of the repo tree."""
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(EXAMPLES_DIR / name))
    return tmp_path / "fv_example_output"


def test_example_01_filters_and_roughness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run_example("01_filters_and_roughness.py", tmp_path, monkeypatch)
    for name in (
        "synthetic_scan.tif",
        "image_stats.csv",
        "roughness.csv",
        "roughness.json",
        "methods.md",
        "provenance.json",
        "session_log.json",
    ):
        assert (out / name).is_file(), f"missing {name}"

    methods_text = (out / "methods.md").read_text(encoding="utf-8")
    assert "gaussian" in methods_text and "median" in methods_text

    roughness = json.loads((out / "roughness.json").read_text(encoding="utf-8"))
    assert roughness["columns"][:2] == ["Ra", "Rq"]

    # provenance.json is scoped to denoised's own image lineage (the two
    # filter steps that produced it); value-only steps run on it afterwards
    # (image_stats, roughness) never produce a new image, so they fall
    # outside any image's ancestry -- only the full session log has all four.
    image_lineage = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert [s["op"] for s in image_lineage] == ["gaussian", "median"]

    full_log = json.loads((out / "session_log.json").read_text(encoding="utf-8"))
    assert [s["op"] for s in full_log] == ["gaussian", "median", "image_stats", "roughness"]


def test_example_02_eds_quantification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run_example("02_eds_quantification.py", tmp_path, monkeypatch)
    for name in (
        "synthetic_eds_cube.hspy",
        "fe_map.tif",
        "si_map.tif",
        "eds_quant.csv",
        "eds_quant.json",
        "eds_provenance.json",
    ):
        assert (out / name).is_file(), f"missing {name}"

    quant = json.loads((out / "eds_quant.json").read_text(encoding="utf-8"))
    assert quant["columns"] == [
        "elements", "lines", "mean_atomic_pct", "mean_weight_pct", "k_factors",
    ]
    row = quant["rows"][0]
    elements = json.loads(row["elements"])
    assert set(elements) == {"Fe", "Si"}


@pytest.mark.realdata
def test_example_03_realdata_dm4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fermiviewer.devsamples import find_sample_files

    if not find_sample_files((".dm4",)):
        pytest.skip("real-instrument corpus (.dm4 sample) not found on this machine")

    out = _run_example("03_realdata_dm4.py", tmp_path, monkeypatch)
    for name in ("realdata_image_stats.csv", "realdata_roughness.csv", "realdata_methods.md"):
        assert (out / name).is_file(), f"missing {name}"

    methods_text = (out / "realdata_methods.md").read_text(encoding="utf-8")
    assert "gaussian" in methods_text and "median" in methods_text
