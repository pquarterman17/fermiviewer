"""Download the local-only real-instrument test corpus (plan item 4).

Port of fermi-viewer's tests/fetchRealEelsData.m. Files land in the
MATLAB repo's +test_datasets/ (shared with the Python suite via the
conftest fixtures); already-present files are skipped.

Sources (see the MATLAB repo's +test_datasets/EELS/README.md):
  - Zenodo 8403583 (CC-BY 4.0) — Burgess et al., lunar sample 79221
    STEM-EELS spectrum images + HAADF + Bruker Esprit EDS map
  - hyperspy/rosettasciio test corpus — tiny GMS EELS SI

Usage:  uv run python tools/fetch_real_data.py
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

_ZENODO = "https://zenodo.org/api/records/8403583/files"

MANIFEST: list[tuple[str, str]] = [
    ("EELS/FigS6_apatite_ZLP.dm4", f"{_ZENODO}/FigS6_apatite_ZLP.dm4/content"),
    (
        "EELS/Fig4_apatite79221_OKedge_vesicle.dm4",
        f"{_ZENODO}/Fig4_apatite79221_OKedge_vesicle.dm4/content",
    ),
    (
        "EELS/Fig4_apatite79221_lowloss_vesicle.dm4",
        f"{_ZENODO}/Fig4_apatite79221_lowloss_vesicle.dm4/content",
    ),
    (
        "EELS/FigS4_apatite79221_F_Fe.dm4",
        f"{_ZENODO}/FigS4_apatite79221_F_Fe.dm4/content",
    ),
    (
        "Microscopy/Fig3c_apatite_HAADF.dm4",
        f"{_ZENODO}/Fig3c_apatite_HAADF.dm4/content",
    ),
    ("BCF/Fig4b_EDSmap_Bruker.bcf", f"{_ZENODO}/Fig4b_EDSmap_Bruker.bcf/content"),
    (
        "EELS/rosettasciio_EELS_SI.dm4",
        "https://raw.githubusercontent.com/hyperspy/rosettasciio/"
        "main/rsciio/tests/data/digitalmicrograph/3D/EELS_SI.dm4",
    ),
]


def dataset_dir() -> Path:
    """../fermi-viewer/+test_datasets relative to this repo."""
    repo = Path(__file__).resolve().parents[1]
    return repo.parent / "fermi-viewer" / "+test_datasets"


def main() -> None:
    ds = dataset_dir()
    print(f"Fetching real-instrument test data into {ds}")
    n_new = 0
    for rel, url in MANIFEST:
        target = ds / rel
        if target.is_file():
            print(f"  . {rel:<45} already present")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"  v {rel:<45} ", end="", flush=True)
        try:
            urllib.request.urlretrieve(url, target)  # noqa: S310 — fixed https manifest
            print(f"{target.stat().st_size / 1e6:.1f} MB")
            n_new += 1
        except OSError as e:
            print(f"FAILED ({e})")
    print(f"Done — {n_new} new file(s) downloaded.")


if __name__ == "__main__":
    main()
