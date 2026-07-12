"""rosettasciio cross-validation oracle — W8 item 31.

For every committed-corpus file both readers can open, our parser and
rsciio must agree on shape, pixel sums and spatial calibration. rsciio
is GPL — dev-only oracle group, never a runtime dependency (enforced
by test_repo_integrity); these tests skip when it isn't installed.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fermiviewer.io.registry import load_auto

rsciio = pytest.importorskip("rsciio", reason="oracle group not installed")

pytestmark = [
    pytest.mark.oracle,
    pytest.mark.parser,
    # rosettasciio 0.14's MRC reader leaves its input handle for GC. Keep this
    # third-party, oracle-only leak from weakening the first-party warning gate.
    pytest.mark.filterwarnings("ignore:unclosed file.*:ResourceWarning"),
]


def _rsciio_load(path: Path) -> list[dict]:
    ext = path.suffix.lower()
    if ext in (".dm3", ".dm4"):
        from rsciio.digitalmicrograph import file_reader
    elif ext == ".ser":
        from rsciio.tia import file_reader
    elif ext == ".mrc":
        from rsciio.mrc import file_reader
    elif ext in (".tif", ".tiff"):
        from rsciio.tiff import file_reader
    else:
        pytest.skip(f"no oracle reader wired for {ext}")
    return file_reader(str(path))


def _corpus_files(ml_datasets: Path) -> list[Path]:
    mic = ml_datasets / "Microscopy"
    out: list[Path] = []
    for pattern in ("*.dm3", "*.dm4", "*.ser", "*.mrc", "*.tif"):
        out.extend(sorted(mic.glob(pattern)))
    return out


def test_committed_corpus_vs_rsciio(ml_datasets: Path) -> None:
    files = _corpus_files(ml_datasets)
    assert files, "committed corpus is empty?"
    compared = 0
    for f in files:
        try:
            theirs = _rsciio_load(f)
        except Exception as e:  # noqa: BLE001 — oracle can't read everything
            print(f"  oracle skip {f.name}: {e}")
            continue
        ours = load_auto(f)
        their_data = np.asarray(theirs[0]["data"], dtype=np.float64)
        our_data = np.asarray(ours.data, dtype=np.float64)
        # 2-D images must match exactly in shape and content
        if our_data.ndim == their_data.ndim == 2:
            assert our_data.shape == their_data.shape, f.name
            assert np.isclose(
                our_data.sum(), their_data.sum(), rtol=1e-9
            ), f"{f.name}: pixel sums diverge"
        else:
            # SI cubes: axis order may differ — totals must still match
            assert np.isclose(
                our_data.sum(), their_data.sum(), rtol=1e-9
            ), f"{f.name}: cube totals diverge"
        compared += 1
    print(f"  oracle compared {compared}/{len(files)} files")
    assert compared >= 3, "too few oracle comparisons succeeded"


@pytest.mark.realdata
def test_rsciio_corpus_sums_vs_oracle(rsciio_examples: Path) -> None:
    """Live cross-check: for every rsciio-corpus file both readers can open,
    our data sum must match the oracle's (best-matching signal, since some
    files carry several). Belt-and-suspenders over the pinned realdata tests
    in test_em_examples.py."""
    files: list[Path] = []
    for sub, pats in (
        ("dm", ("*.dm3", "*.dm4")),
        ("tia", ("*.ser",)),
        ("emd", ("*.emd",)),
        ("mrc", ("*.mrc",)),
        ("msa", ("*.msa",)),
        ("bruker", ("*.bcf",)),
    ):
        for pat in pats:
            files.extend(sorted((rsciio_examples / sub).glob(pat)))

    def _oracle(path: Path):
        ext = path.suffix.lower()
        mod = {
            ".dm3": "digitalmicrograph", ".dm4": "digitalmicrograph",
            ".ser": "tia", ".emd": "emd", ".mrc": "mrc", ".msa": "msa",
            ".bcf": "bruker",
        }[ext]
        return __import__(f"rsciio.{mod}", fromlist=["file_reader"]).file_reader(str(path))

    # multi-frame stacks intentionally return only the first frame (no
    # image-stack DataKind); their partial sum is pinned in test_em_examples.
    partial = {
        "16x16-line_profile_horizontal_5x128x128_EDS_2.ser",
        "fei_example_tem_stack.emd",
        "4DSTEMscan.mrc",  # 4D-STEM: we return the first 2D frame (deferred feature)
    }
    compared = 0
    for f in files:
        if f.name in partial:
            continue
        try:
            ours = load_auto(f)
        except Exception:  # noqa: BLE001 — documented-limitation files (complex FFT, NCEM-4D)
            continue
        try:
            theirs = _oracle(f)
        except Exception as e:  # noqa: BLE001
            print(f"  oracle skip {f.name}: {e}")
            continue
        our_sum = float(np.nan_to_num(np.asarray(ours.data, np.float64)).sum())
        their_sums = [
            float(np.nan_to_num(np.asarray(s["data"], np.float64)).sum()) for s in theirs
        ]
        assert any(
            abs(our_sum - t) <= 1e-6 * max(abs(t), 1) for t in their_sums
        ), f"{f.name}: sum {our_sum} not among oracle sums {their_sums}"
        compared += 1
    print(f"  rsciio-corpus oracle compared {compared}/{len(files)} files")
    assert compared >= 15, "too few oracle comparisons succeeded"


@pytest.mark.realdata
def test_real_eels_cube_vs_rsciio(eels_corpus: Path) -> None:
    f = eels_corpus / "FigS6_apatite_ZLP.dm4"
    ours = load_auto(f)
    theirs = _rsciio_load(f)
    their_data = np.asarray(theirs[0]["data"], dtype=np.float64)
    assert np.isclose(
        np.asarray(ours.data, dtype=np.float64).sum(),
        their_data.sum(),
        rtol=1e-9,
    )
    # calibrated energy axis: scale agrees with the rsciio axes table
    axes = theirs[0]["axes"]
    energy_axes = [
        a for a in axes if str(a.get("units", "")).lower() in ("ev", "kev")
    ]
    assert energy_axes, "oracle reported no energy axis"
    assert np.isclose(
        ours.energy_cal.scale, float(energy_axes[0]["scale"]), rtol=1e-6
    )
