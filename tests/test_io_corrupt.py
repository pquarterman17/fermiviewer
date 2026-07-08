"""Cross-cutting io/ robustness tests that don't belong to one parser file.

Currently: a single parametrized round-trip of every parser's minimal
fixture through a Unicode + space path component (``möss bär``) — there was
zero such coverage before this, and Windows/OneDrive paths regularly contain
both.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest
import tifffile
from PIL import Image

from fermiviewer.datastruct import DataKind
from fermiviewer.io.registry import load_auto
from fixtures.minidm4 import write_mini_dm4
from fixtures.minimrc import write_mini_mrc
from fixtures.minisfs import write_mini_sfs_bcf
from fixtures.ser import write_ser_spectra

pytestmark = pytest.mark.parser


def _bcf_xml(n_chan: int) -> bytes:
    counts = ",".join(str(v) for v in range(1, n_chan + 1))
    return (
        f'<ClassInstance Type="TRTSpectrumHeader">'
        f"<CalibAbs>-0.5</CalibAbs><CalibLin>0.01</CalibLin></ClassInstance>"
        f"<ChCount>{n_chan}</ChCount><Channels>{counts}</Channels>"
    ).encode()


def _make_dm4(d: Path) -> Path:
    return write_mini_dm4(
        d / "a.dm4", dims=[3, 2], data=np.arange(6),
        cal=[{"scale": 1, "origin": 0, "units": "nm"}] * 2,
    )


def _make_ser(d: Path) -> Path:
    p = d / "b.ser"
    write_ser_spectra(p, scan_dims=[], n_channels=4)
    return p


def _make_mrc(d: Path) -> Path:
    p = d / "c.mrc"
    write_mini_mrc(p, np.arange(9, dtype=np.uint16).reshape(3, 3), mode=6)
    return p


def _make_msa(d: Path) -> Path:
    p = d / "d.msa"
    p.write_text(
        "#FORMAT : EMSA/MAS Spectral Data File\n#XUNITS : eV\n"
        "#XPERCHAN : 1.0\n#DATATYPE : Y\n#SPECTRUM :\n1.0, 2.0, 3.0\n#ENDOFDATA\n"
    )
    return p


def _make_tiff(d: Path) -> Path:
    p = d / "e.tif"
    tifffile.imwrite(p, np.arange(12, dtype=np.uint16).reshape(3, 4))
    return p


def _make_png(d: Path) -> Path:
    p = d / "f.png"
    Image.fromarray(np.arange(12, dtype=np.uint8).reshape(3, 4)).save(p)
    return p


def _make_bcf(d: Path) -> Path:
    return write_mini_sfs_bcf(d / "g.bcf", _bcf_xml(4))


def _make_hspy(d: Path) -> Path:
    p = d / "h.hspy"
    with h5py.File(p, "w") as fh:
        exp = fh.create_group("Experiments/sig")
        exp.create_dataset("data", data=np.arange(12, dtype=np.float32).reshape(3, 4))
        for i, (name, units) in enumerate([("y", "nm"), ("x", "nm")]):
            g = exp.create_group(f"axis-{i}")
            g.attrs["scale"], g.attrs["offset"] = 1.0, 0.0
            g.attrs["units"], g.attrs["name"] = units, name
            g.attrs["navigate"] = True
    return p


def _make_nexus(d: Path) -> Path:
    p = d / "i.nxs"
    with h5py.File(p, "w") as fh:
        fh.attrs["default"] = "entry"
        entry = fh.create_group("entry")
        entry.attrs["NX_class"], entry.attrs["default"] = "NXentry", "data"
        data = entry.create_group("data")
        data.attrs["NX_class"], data.attrs["signal"] = "NXdata", "sig"
        data.attrs["axes"] = ["y", "x"]
        data.create_dataset("sig", data=np.arange(12, dtype=np.float32).reshape(3, 4))
        for name, vals in (("y", np.arange(3) * 1.0), ("x", np.arange(4) * 1.0)):
            dd = data.create_dataset(name, data=vals)
            dd.attrs["units"] = "nm"
    return p


@pytest.mark.parametrize(
    "make, expect_kind",
    [
        (_make_dm4, DataKind.IMAGE),
        (_make_ser, DataKind.SPECTRUM),
        (_make_mrc, DataKind.IMAGE),
        (_make_msa, DataKind.SPECTRUM),
        (_make_tiff, DataKind.IMAGE),
        (_make_png, DataKind.IMAGE),
        (_make_bcf, DataKind.SPECTRUM),
        (_make_hspy, DataKind.IMAGE),
        (_make_nexus, DataKind.IMAGE),
    ],
    ids=["dm4", "ser", "mrc", "msa", "tiff", "png", "bcf", "hspy", "nxs"],
)
def test_unicode_space_path_roundtrip(tmp_path, make, expect_kind) -> None:
    unicode_dir = tmp_path / "möss bär"
    unicode_dir.mkdir()
    f = make(unicode_dir)
    ds = load_auto(f)
    assert ds.kind is expect_kind
    assert ds.metadata["source"] == str(f)
