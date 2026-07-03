"""Shared fixtures: golden loading + local-corpus discovery."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make tests/fixtures/ importable (synthetic file generators)
sys.path.insert(0, str(Path(__file__).parent))

GOLDEN_DIR = Path(__file__).parent / "golden"
ML_ROOT = Path(__file__).resolve().parents[2] / "fermi-viewer"


@pytest.fixture(scope="session")
def golden():
    """Load a golden JSON by stem: golden('eels_realdata')."""

    def _load(stem: str) -> dict:
        return json.loads((GOLDEN_DIR / f"{stem}.json").read_text())

    return _load


@pytest.fixture(scope="session")
def ml_datasets() -> Path:
    """Path to the MATLAB repo's test datasets (committed corpus).

    Skips the test when fermi-viewer is not checked out alongside this
    repo (e.g. minimal CI checkout) — golden-only tests still run.
    """
    p = ML_ROOT / "+test_datasets"
    if not p.is_dir():
        pytest.skip("fermi-viewer test datasets not present")
    return p


@pytest.fixture(scope="session")
def eels_corpus(ml_datasets: Path) -> Path:
    """Local-only real EELS corpus; skips when absent (fetch script)."""
    p = ml_datasets / "EELS"
    if not (p / "FigS6_apatite_ZLP.dm4").is_file():
        pytest.skip("local EELS corpus absent — run fetch script")
    return p


# Sibling example-dataset repo (../fv-example-data) — real BCF corpus for
# TEM/SEM EDS, kept out of this repo (GPL data). See its README.
EXAMPLE_DATA_ROOT = Path(__file__).resolve().parents[2] / "fv-example-data"


@pytest.fixture(scope="session")
def bcf_examples() -> Path:
    """Path to ../fv-example-data/BCF; skips when the corpus isn't present."""
    p = EXAMPLE_DATA_ROOT / "BCF"
    if not (p / "SEM" / "Hitachi_TM3030Plus.bcf").is_file():
        pytest.skip("fv-example-data BCF corpus absent (sibling repo)")
    return p
