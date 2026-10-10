"""AFM/SPM file formats beyond Bruker NanoScope: Gwyddion .gwy, Asylum
.ibw, JPK .jpk, WSxM .top/.stp — synthetic files for CI, real instrument
files from the corpus when present — plus opening their other channels."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.io.gwy import GwyError, load_gwy, load_gwy_all
from fermiviewer.io.ibw import IbwError, load_ibw_all
from fermiviewer.io.jpk import JpkError, load_jpk, load_jpk_all
from fermiviewer.io.registry import load_auto, supported_extensions
from fermiviewer.io.spm_channels import load_spm_channels
from fermiviewer.io.spm_common import primary_channel
from fermiviewer.io.wsxm import WsxmError, load_wsxm
from fermiviewer.server import ALLOWED_HOSTS, create_app
from fermiviewer.session import store
from fixtures.minispm import write_gwy, write_ibw, write_jpk, write_wsxm

ALLOWED_HOSTS.add("testserver")
RAMP = np.arange(12, dtype=float).reshape(3, 4)       # rows top→bottom, distinct values


# ── Gwyddion ─────────────────────────────────────────────────────────

def test_gwy_channels_units_and_orientation(tmp_path) -> None:
    p = write_gwy(tmp_path / "a.gwy", [("Phase", RAMP, "deg"), ("Height", RAMP * 1e-9, "m")])
    chans = load_gwy_all(p)
    assert [c.metadata["channel"] for c in chans] == ["Phase", "Height"]
    h = load_gwy(p)                                     # topography wins over channel order
    assert h.metadata["channel"] == "Height" and h.metadata["value_unit"] == "nm"
    np.testing.assert_allclose(h.data, RAMP)            # m → nm; top row first
    assert h.axes[1].scale == pytest.approx(1000 / 4) and h.axes[0].scale == pytest.approx(1000 / 3)
    assert chans[0].metadata["value_unit"] == "deg"


def test_gwy_rejects_other_files(tmp_path) -> None:
    (tmp_path / "x.gwy").write_bytes(b"GWYO....")                 # truncated 1.x
    with pytest.raises(GwyError):
        load_gwy_all(tmp_path / "x.gwy")
    (tmp_path / "z.gwy").write_bytes(b"PK\x03\x04")
    with pytest.raises(GwyError, match="not a Gwyddion"):
        load_gwy_all(tmp_path / "z.gwy")
    (tmp_path / "y.gwy").write_bytes(b"GWYP" + b"Gwy")      # truncated
    with pytest.raises(GwyError):
        load_gwy_all(tmp_path / "y.gwy")


# ── Asylum IBW ───────────────────────────────────────────────────────

def test_ibw_layers_become_labelled_channels(tmp_path) -> None:
    p = write_ibw(tmp_path / "s.ibw", {
        "HeightTrace": RAMP * 1e-9, "HeightRetrace": RAMP * 2e-9, "PhaseTrace": RAMP,
        "ZSensorTrace": RAMP,
    }, dx_m=2e-9, note="ZLVDTSens: -1\rUserIn0Unit: V\r")
    chans = {c.metadata["channel_label"]: c for c in load_ibw_all(p)}
    assert list(chans) == ["Height (trace)", "Height (retrace)", "Phase (trace)", "ZSensor (trace)"]
    np.testing.assert_allclose(chans["Height (trace)"].data, RAMP, rtol=1e-6)
    assert chans["Height (trace)"].metadata["value_unit"] == "nm"
    assert chans["Height (trace)"].axes[1].scale == pytest.approx(2.0)
    assert chans["Phase (trace)"].metadata["value_unit"] == "°"
    # an uncalibrated Z LVDT saves volts, not metres
    assert chans["ZSensor (trace)"].metadata["value_unit"] == "V"


def test_ibw_rejects_a_non_image_wave(tmp_path) -> None:
    (tmp_path / "x.ibw").write_bytes(b"\x02\x00" + bytes(500))
    with pytest.raises(IbwError, match="version 5"):
        load_ibw_all(tmp_path / "x.ibw")


# ── JPK ──────────────────────────────────────────────────────────────

def test_jpk_default_slot_scaling_and_trace_first(tmp_path) -> None:
    raw = np.arange(16, dtype=np.int32).reshape(4, 4)
    p = write_jpk(tmp_path / "s.jpk", {("height", True): raw * 2, ("height", False): raw,
                                       ("error", False): raw},
                  mult=1e-9, off=5e-9, size_m=4e-9)
    chans = load_jpk_all(p)
    assert [c.metadata["channel_label"] for c in chans] == \
        ["Height (trace)", "Error (trace)", "Height (retrace)"]
    h = load_jpk(p)
    assert h.metadata["channel_label"] == "Height (trace)"
    np.testing.assert_allclose(h.data, np.flipud(raw) + 5.0)      # raw·1 nm + 5 nm, top row first
    assert h.metadata["value_unit"] == "nm" and h.axes[1].scale == pytest.approx(1.0)
    assert chans[1].metadata["value_unit"] == "V"


def test_jpk_rejects_a_plain_tiff(tmp_path) -> None:
    import tifffile

    tifffile.imwrite(tmp_path / "x.jpk", np.zeros((4, 4), np.uint8))
    with pytest.raises(JpkError):
        load_jpk_all(tmp_path / "x.jpk")


# ── WSxM ─────────────────────────────────────────────────────────────

def test_wsxm_short_spans_the_z_amplitude_and_is_rotated(tmp_path) -> None:
    stored = np.array([[0, 1], [2, 4]], dtype=np.int16)
    ds = load_wsxm(write_wsxm(tmp_path / "s.top", stored, "short", "8 nm", amp="2 µm"))
    np.testing.assert_allclose(ds.data, [[8, 4], [2, 0]])        # 180°, 4 counts = 8 nm
    assert ds.axes[1].scale == pytest.approx(1000.0)            # 2 µm / 2 px
    assert ds.metadata["channel_label"] == "Topography (retrace)"


def test_wsxm_double_is_already_in_z_units(tmp_path) -> None:
    stored = np.array([[1.5, 2.5], [3.5, 4.5]])
    ds = load_wsxm(write_wsxm(tmp_path / "s.stp", stored, "double", "3 nm"))
    np.testing.assert_allclose(ds.data, stored[::-1, ::-1])
    with pytest.raises(WsxmError):
        (tmp_path / "x.top").write_bytes(b"WSxM file copyright\r\nno size here")
        load_wsxm(tmp_path / "x.top")


# ── registry and channel access ──────────────────────────────────────

def test_registry_routes_every_spm_extension(tmp_path) -> None:
    assert {".gwy", ".ibw", ".jpk", ".jpk-qi-image", ".top", ".stp"} <= set(supported_extensions())
    p = write_gwy(tmp_path / "a.gwy", [("Height", RAMP * 1e-9, "m")])
    assert load_auto(p).metadata["parser"] == "gwyddion"
    assert len(load_spm_channels(p)) == 1


def test_primary_channel_prefers_an_exact_name() -> None:
    from fermiviewer.io.spm_common import spm_channel

    mk = [spm_channel(RAMP, parser="x", channel=n, label=n, value_unit="", dy_nm=1, dx_nm=1)
          for n in ("Height (measured)", "Phase", "Height")]
    assert primary_channel(mk).metadata["channel"] == "Height"


@pytest.fixture()
def client():
    from fermiviewer.routes.afm import reset

    store.clear()
    reset()
    yield TestClient(create_app())
    store.clear()
    reset()


def test_other_channels_open_for_a_gwy_file_and_an_upload(client, tmp_path) -> None:
    p = write_gwy(tmp_path / "s.gwy", [("Height", RAMP * 1e-9, "m"), ("Phase", RAMP, "deg"),
                                       ("Adhesion", RAMP, "N")])
    meta = client.post("/api/session/open", json={"paths": [str(p)]}).json()[0]
    assert meta["name"] == "s.gwy"
    names = [m["name"] for m in client.post(f"/api/afm/{meta['id']}/channels").json()]
    assert names == ["s.gwy · Phase", "s.gwy · Adhesion"]
    with p.open("rb") as f:
        up = client.post("/api/session/upload",
                         files=[("files", ("u.gwy", f, "application/octet-stream"))]).json()[0]
    assert len(client.post(f"/api/afm/{up['id']}/channels").json()) == 2


# ── real instrument files (sibling corpus) ───────────────────────────

def _corpus(rel: str) -> Path:
    from conftest import EXAMPLE_DATA_ROOT

    p = EXAMPLE_DATA_ROOT / rel
    if not p.is_file():
        pytest.skip(f"corpus file absent: {rel}")
    return p


def test_real_gwy_peakforce_export() -> None:
    chans = load_gwy_all(_corpus("gwyddion/afm/afmreader_sample_0.gwy"))
    assert len(chans) == 8 and primary_channel(chans).metadata["channel"] == "Height"
    h = primary_channel(chans)
    assert h.data.shape == (512, 512) and np.ptp(h.data) == pytest.approx(25.28, abs=0.05)


def test_real_ibw_asylum_scan() -> None:
    chans = load_ibw_all(_corpus("asylum/afm/afmreader_sample_0.ibw"))
    assert len(chans) == 8
    h = primary_channel(chans)
    assert h.metadata["channel_label"] == "Height (trace)"
    assert h.axes[1].scale == pytest.approx(800 / 511, rel=1e-6)   # 800 nm scan, sfA
    assert np.ptp(h.data) == pytest.approx(23.26, abs=0.05)


@pytest.mark.parametrize("name,n", [("afmreader_sample_0.jpk", 10),
                                    ("afmreader_sample_0.jpk-qi-image", 6)])
def test_real_jpk(name, n) -> None:
    chans = load_jpk_all(_corpus(f"jpk/afm/{name}"))
    labels = [c.metadata["channel_label"] for c in chans]
    assert len(chans) == n and len(set(labels)) == n          # repeated names numbered
    assert primary_channel(chans).metadata["channel_label"] == "Height (trace)"


@pytest.mark.parametrize("stem,zrange,px", [("afmreader_sample_0", 59.7449, 500 / 512),
                                            ("afmreader_sample_1_um_scale", 4.53125, 2000 / 512)])
def test_real_wsxm_top_and_stp_agree(stem, zrange, px) -> None:
    top = load_wsxm(_corpus(f"wsxm/afm/{stem}.top"))
    stp = load_wsxm(_corpus(f"wsxm/afm/{stem}.stp"))
    assert np.ptp(top.data) == pytest.approx(zrange) and top.axes[1].scale == pytest.approx(px)
    np.testing.assert_allclose(top.data - top.data.mean(), stp.data - stp.data.mean(), atol=1e-9)


# ── Gwyddion simple field and 1.x, Nanosurf, NT-MDT, Nanonis ─────────

from fermiviewer.io.gwy import load_gsf  # noqa: E402
from fermiviewer.io.mdt import MdtError, load_mdt_all  # noqa: E402
from fermiviewer.io.nid import NidError, load_nid, load_nid_all  # noqa: E402
from fermiviewer.io.sxm import SxmError, load_sxm, load_sxm_all  # noqa: E402
from fixtures.minispm import write_gsf, write_gwyo, write_mdt, write_nid, write_sxm  # noqa: E402


def test_gsf_and_gwyddion_1x(tmp_path) -> None:
    g = load_gsf(write_gsf(tmp_path / "a.gsf", RAMP * 1e-9, 1e-6, title="Topo"))
    np.testing.assert_allclose(g.data, RAMP, rtol=1e-6)
    assert g.metadata["channel"] == "Topo" and g.axes[0].scale == pytest.approx(1000 / 3)
    old = load_gwy_all(write_gwyo(tmp_path / "o.gwy", RAMP * 1e-9, 1e-6))
    assert len(old) == 1 and old[0].metadata["value_unit"] == "nm"
    np.testing.assert_allclose(old[0].data, RAMP)


def test_nid_scaling_and_orientation(tmp_path) -> None:
    raw = np.array([[-2**31, 0], [2**30, 2**31 - 1]], dtype=np.int64)
    p = write_nid(tmp_path / "s.nid", [("Z-Axis", "m", raw), ("Phase", "deg", raw)],
                  range_m=2e-6, zmin=-1e-6, zrange=4e-6)
    z = load_nid(p)
    assert z.metadata["channel_label"] == "Z-Axis (trace)" and z.metadata["value_unit"] == "nm"
    # min + range·(raw + 2³¹)/2³², lines bottom-up → top row first
    frac = (raw.astype(float) + 2**31) / 2**32
    np.testing.assert_allclose(z.data, np.flipud(-1000 + 4000 * frac))
    assert z.axes[1].scale == pytest.approx(1000.0)
    assert [c.metadata["value_unit"] for c in load_nid_all(p)] == ["nm", "deg"]
    (tmp_path / "x.nid").write_bytes(b"[DataSet]\r\nGroupCount=1\r\n")
    with pytest.raises(NidError):
        load_nid_all(tmp_path / "x.nid")


def test_nid_steps_over_one_line_blocks(tmp_path) -> None:
    """A spectroscopy line listed before an image still owns its bytes:
    the image must be read from its own block, not the line's."""
    line = np.arange(5, dtype=np.int64).reshape(1, 5) * 1000
    img = np.array([[1, 2], [3, 4]], dtype=np.int64) * 2**20
    p = write_nid(tmp_path / "m.nid", [("Spec", "N", line), ("Z-Axis", "m", img)],
                  range_m=2e-6, zmin=0.0, zrange=1e-6)
    (z,) = load_nid_all(p)
    frac = (img.astype(float) + 2**31) / 2**32
    np.testing.assert_allclose(z.data, np.flipud(1000 * frac))


def test_mdt_scanned_and_mda_frames(tmp_path) -> None:
    scanned = np.array([[0, 2, 4], [6, 8, 10]], dtype=np.int16)
    mda = np.array([[0, 4], [8, 12], [16, 20]], dtype=np.int32)
    chans = load_mdt_all(write_mdt(tmp_path / "s.mdt", scanned, mda, step_nm=2.0))
    topo, phase = chans
    assert topo.metadata["channel"] == "Topography" and topo.metadata["value_unit"] == "nm"
    np.testing.assert_allclose(topo.data, np.flipud(5 + 0.5 * scanned))
    assert topo.axes[1].scale == pytest.approx(2.0)
    assert phase.metadata["channel"] == "Phase" and phase.metadata["value_unit"] == "deg"
    np.testing.assert_allclose(phase.data, np.flipud(1 + 0.25 * mda))
    assert phase.axes[1].scale == pytest.approx(2.0)                    # 0.002 µm → nm
    (tmp_path / "x.mdt").write_bytes(b"\x01\xb0\x93\xff" + bytes(29))
    with pytest.raises(MdtError):
        load_mdt_all(tmp_path / "x.mdt")


def test_sxm_backward_is_mirrored_and_up_scans_flipped(tmp_path) -> None:
    fwd = RAMP * 1e-9
    p = write_sxm(tmp_path / "s.sxm", fwd, fwd * 2, range_m=4e-9)
    z, zb = load_sxm_all(p)
    assert z.metadata["channel_label"] == "Z (trace)"
    assert zb.metadata["channel_label"] == "Z (retrace)"
    np.testing.assert_allclose(z.data, np.flipud(RAMP), rtol=1e-6)            # scanned up
    np.testing.assert_allclose(zb.data, np.flipud(2 * RAMP)[:, ::-1], rtol=1e-6)
    assert z.axes[1].scale == pytest.approx(1.0)
    down = load_sxm(write_sxm(tmp_path / "d.sxm", fwd, fwd, 4e-9, direction="down"))
    np.testing.assert_allclose(down.data, RAMP, rtol=1e-6)
    (tmp_path / "x.sxm").write_bytes(b":NANONIS_VERSION:\n2\n")
    with pytest.raises(SxmError, match="marker"):
        load_sxm_all(tmp_path / "x.sxm")


def test_ampere_is_not_an_angstrom() -> None:
    from fermiviewer.io.spm_common import length_to_nm_factor

    assert length_to_nm_factor("A") is None and length_to_nm_factor("Å") == pytest.approx(0.1)


def test_non_image_spm_files_are_refused(tmp_path) -> None:
    from fermiviewer.io.registry import UnsupportedFormatError

    (tmp_path / "c.curves").write_bytes(b"WSxM file copyright UAM\r\nWSxM Lithography curves\r\n")
    with pytest.raises(UnsupportedFormatError):
        load_auto(tmp_path / "c.curves")
    p = write_wsxm(tmp_path / "x.f.dy.ch3", np.zeros((2, 2), np.int16), "short", "1 nm")
    assert load_auto(p).metadata["parser"] == "wsxm"       # any extension, by content


# ── more real instrument files ───────────────────────────────────────

def test_real_nid_matches_nsfopen() -> None:
    """Nanosurf's own NSFopen reader gives this sapphire scan (in its file
    order, i.e. before our bottom-up flip): mean −3421.98 nm, σ 15.22 nm."""
    z = load_nid(_corpus("nanosurf/afm/nsfopen_sapphire.nid"))
    assert z.metadata["channel_label"] == "Z-Axis (trace)" and z.data.shape == (256, 256)
    assert z.data.mean() == pytest.approx(-3421.9843541317077, rel=1e-12)
    assert z.data.std() == pytest.approx(15.222071245522843, rel=1e-9)
    assert z.data[0, 0] == pytest.approx(-3449.7025077044964)
    assert z.axes[1].scale == pytest.approx(9.765625)
    assert len(load_nid_all(_corpus("nanosurf/afm/nsfopen_MoS2.nid"))) == 8


def test_real_mdt_matches_pycroscopy() -> None:
    (img,) = load_mdt_all(_corpus("ntmdt/afm/pycroscopy_test_mdt.mdt"))
    assert img.metadata["channel"] == "1F:Iprobe" and img.metadata["value_unit"] == "nA"
    assert img.data.mean() == pytest.approx(0.11146018657195313, rel=1e-9)
    assert img.data.std() == pytest.approx(1.718831390695344, rel=1e-9)
    assert img.axes[1].scale == pytest.approx(11.767974683082528)


def test_real_sxm_matches_pycroscopy() -> None:
    chans = load_sxm_all(_corpus("nanonis/stm/pycroscopy_NanonisReader_COOx_sample2286.sxm"))
    assert len(chans) == 20
    z = primary_channel(chans)
    assert z.metadata["channel_label"] == "Z (trace)"
    assert z.data.mean() == pytest.approx(109.02276452397133, rel=1e-6)
    assert z.data[0, 0] == pytest.approx(109.60082619249079, rel=1e-6)


@pytest.mark.parametrize("rel,label,unit", [
    ("gwyddion/afm/pycroscopy_GwiddionReader_chip.gwy", "Channel 0", "nm"),       # Gwyddion 1.x
    ("gwyddion/afm/pycroscopy_GwiddionReader_chip.gsf", "Topography", "nm"),
    ("asylum/afm/pycroscopy_IgorIBWReader_P0089OP0027.ibw", "Height (retrace)", "nm"),
    ("asylum/afm/pycroscopy_20230110-152047_ScV6Sn6-2023-01-10-STM_NANOPROBE_"
     "AtomManipulation--37_1-I_3_Backward_Down.ibw", "I 3 37-1 Backward Down", "A"),
    ("wsxm/afm/pycroscopy_WSxM2DReader_jumpingmodeimage_0002_Adhesion.f.dy.jm.adh",
     "Adhesion (trace)", "V"),
    ("bruker/afm/pycroscopy_BrukerReader_Image.001", "Height Sensor (retrace)", "nm"),
])
def test_real_files_open_with_their_units(rel, label, unit) -> None:
    ds = load_auto(_corpus(rel))
    assert ds.metadata["channel_label"] == label and ds.metadata["value_unit"] == unit


@pytest.mark.parametrize("rel,match", [
    ("asylum/afm/pycroscopy_IgorIBWReader_ForceCurve.ibw", "curve"),
    ("asylum/afm/pycroscopy_20230110-152047_ScV6Sn6-2023-01-10-STM_NANOPROBE_"
     "AtomManipulation--37_1-Aux2(V)_3_Forward_Down_Trace.ibw", "spectroscopy grid"),
    ("nanosurf/afm/nsfopen_thermal.nid", "no image"),
])
def test_real_non_images_are_refused_clearly(rel, match) -> None:
    with pytest.raises(ValueError, match=match):
        load_auto(_corpus(rel))
