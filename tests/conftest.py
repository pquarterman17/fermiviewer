"""Shared fixtures: golden loading + local-corpus discovery."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from fermiviewer.devsamples import corpus_root
from fermiviewer.server import ALLOWED_HOSTS

# Make tests/fixtures/ importable (synthetic file generators)
sys.path.insert(0, str(Path(__file__).parent))

GOLDEN_DIR = Path(__file__).parent / "golden"
# Single source of truth for corpus discovery (see devsamples.corpus_root):
# duplicating the walk here is what let the two drift when the checkouts
# moved off OneDrive, silently skipping every realdata/golden test.
ML_ROOT = corpus_root()

# server.py's Host-header guard (DNS-rebinding defense) only allows this
# app's own hostnames. FastAPI's TestClient sends `Host: testserver`, so
# every test in the suite would 403 without this — extended here, in the
# ONE place all ~40 `TestClient(create_app())` call sites share, instead
# of a per-file fixture or per-request header. Production's default set
# (127.0.0.1/localhost/::1) never includes "testserver".
ALLOWED_HOSTS.add("testserver")


@pytest.fixture(scope="session")
def golden():
    """Load a golden JSON by stem: golden('eels_realdata')."""

    def _load(stem: str) -> dict:
        return json.loads((GOLDEN_DIR / f"{stem}.json").read_text())

    return _load


@pytest.fixture(scope="session")
def ml_datasets() -> Path:
    """Path to the MATLAB repo's test datasets (committed corpus).

    Skips the test when fermi-viewer is not checked out (e.g. minimal CI
    checkout) — golden-only tests still run.
    """
    p = ML_ROOT / "+test_datasets"
    if not p.is_dir():
        # Name the path. A bare "not present" is indistinguishable from
        # "the corpus moved", which is how a whole realdata suite went
        # quiet for a day without anyone noticing.
        pytest.skip(
            f"fermi-viewer test datasets not present at {p} "
            f"(set FV_MATLAB_ROOT to override)"
        )
    return p


@pytest.fixture(scope="session")
def eels_corpus(ml_datasets: Path) -> Path:
    """Local-only real EELS corpus; skips when absent (fetch script)."""
    p = ml_datasets / "EELS"
    if not (p / "FigS6_apatite_ZLP.dm4").is_file():
        pytest.skip("local EELS corpus absent — run fetch script")
    return p


# Sibling instrument corpus (../test-data), which absorbed fv-example-data on
# 2026-07-25 — one private corpus repo instead of two. The split had started
# leaking: both repos held Bruker NanoScope .spm parsed by the same reader.
#
# The corpus is organized <vendor>/<technique>/, and filenames carry a
# "<source>_" prefix recording provenance (rosettasciio_, topostats_, pyspm_,
# zenodo8403583_, internal_). Per-file licensing lives in each vendor's
# MANIFEST.md — the corpus is mixed GPL-3.0 / CC-BY-4.0 / internal, which is
# why it stays private.
EXAMPLE_DATA_ROOT = Path(__file__).resolve().parents[2] / "test-data"


@pytest.fixture(scope="session")
def bcf_examples() -> Path:
    """Path to ../test-data/bruker/eds; skips when the corpus isn't present."""
    p = EXAMPLE_DATA_ROOT / "bruker" / "eds"
    if not (p / "Hitachi_TM3030Plus.bcf").is_file():
        pytest.skip(f"test-data BCF corpus absent at {p} (sibling repo)")
    return p


@pytest.fixture(scope="session")
def afm_examples() -> Path:
    """Path to ../test-data/bruker/afm; skips when the corpus isn't present.

    Real Bruker NanoScope files (TopoStats + pySPM); see the corpus MANIFEST.
    """
    p = EXAMPLE_DATA_ROOT / "bruker" / "afm"
    if not (p / "topostats_minicircle.spm").is_file():
        pytest.skip(f"test-data AFM corpus absent at {p} (sibling repo)")
    return p


@pytest.fixture(scope="session")
def rsciio_examples() -> Path:
    """Corpus root for the rosettasciio-derived TEM/STEM/EDS/EELS files.

    Returns the ``test-data`` root rather than one subdirectory: the former
    ``rsciio/`` tree was redistributed across vendors during the merge
    (``dm`` -> ``gatan``, ``tia`` -> ``fei``), plus vendor-neutral format
    families (``emd``, ``mrc``, ``emsa``), so callers pass full
    ``<vendor>/<technique>/<file>`` paths. Cross-validated against the
    rosettasciio oracle; see each vendor's MANIFEST.md.
    """
    p = EXAMPLE_DATA_ROOT
    if not (p / "gatan" / "microscopy" / "rosettasciio_test_STEM_image.dm3").is_file():
        pytest.skip(f"test-data rsciio corpus absent at {p} (sibling repo)")
    return p


@pytest.fixture(scope="session")
def gatan_microscopy() -> Path:
    """Path to ../test-data/gatan/microscopy; skips when absent.

    Holds DM images that the golden manifest still keys by their original
    MATLAB filename but that left fermi-viewer's committed corpus in the
    2026-07-25 consolidation; see RELOCATED in test_dm_golden.py.
    """
    p = EXAMPLE_DATA_ROOT / "gatan" / "microscopy"
    if not (p / "zenodo8403583_apatite_HAADF.dm4").is_file():
        pytest.skip(f"test-data Gatan corpus absent at {p} (sibling repo)")
    return p
