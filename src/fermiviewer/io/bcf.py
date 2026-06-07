"""Bruker BCF (Esprit) EDS spectral-imaging parser.

Port of fermi-viewer's importBCF.m + decodeBcfCube.m. The container is
SFS (io/sfs.py); HeaderData is XML (parsed with tolerant regexes — the
giant base64 <Data> blocks defeat real XML parsers); SpectrumData0 is
the packed per-pixel hypercube (16-bit raw / 12-bit packed / instructive
run-length — a faithful port of the HyperSpy-pinned decoder).

Energy convention: E_keV = CalibAbs + CalibLin · channel, expressed as
AxisCal(scale=CalibLin, origin=−CalibAbs/CalibLin).

Returned DataStruct priority: decoded cube → SPECTRUM_IMAGE; else SEM
image → IMAGE; else header sum spectrum → SPECTRUM. Companions ride in
metadata (sem_image, sum_spectrum, elements, sem_params).
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.bcf_cube import decode_cube
from fermiviewer.io.sfs import SfsFile, decompress_if_aacs

__all__ = ["load_bcf"]


# ── XML helpers (regex-tolerant) ─────────────────────────────────────

def _tag_text(xml: str, tag: str) -> str:
    m = re.search(f"<{tag}>(.+?)</{tag}>", xml, re.S)
    return m.group(1) if m else ""


def _tag_float(xml: str, tag: str) -> float:
    t = _tag_text(xml, tag).strip()
    try:
        return float(t)
    except ValueError:
        return float("nan")


def _class_blocks(xml: str, type_name: str, first_only: bool = False) -> list[str]:
    """Inner content of <ClassInstance Type="...">, depth-counted."""
    out = []
    for m in re.finditer(f'Type="{type_name}"', xml):
        start = xml.find(">", m.end())
        if start < 0:
            break
        depth, pos = 1, start + 1
        while depth > 0:
            nxt_open = xml.find("<ClassInstance", pos)
            nxt_close = xml.find("</ClassInstance>", pos)
            if nxt_close < 0:
                pos = len(xml)
                break
            if 0 <= nxt_open < nxt_close:
                depth += 1
                pos = nxt_open + 14
            else:
                depth -= 1
                pos = nxt_close + 16
        out.append(xml[start + 1 : pos])
        if first_only:
            break
    return out


def _sem_params(xml: str) -> dict[str, float]:
    out: dict[str, float] = {}
    sem = _class_blocks(xml, "TRTSEMData", first_only=True)
    if sem:
        out["voltage_kV"] = _tag_float(sem[0], "HV")
        dx = _tag_float(sem[0], "DX")
        if np.isfinite(dx) and dx > 0:
            out["pixel_size_um"] = dx
        out["magnification"] = _tag_float(sem[0], "Mag")
    stage = _class_blocks(xml, "TRTSEMStageData", first_only=True)
    if stage:
        for tag, key in (("X", "stage_x_mm"), ("Y", "stage_y_mm"),
                         ("Tilt", "stage_tilt_deg")):
            out[key] = _tag_float(stage[0], tag)
    esma = _class_blocks(xml, "TRTESMAHeader", first_only=True)
    if esma:
        out["elevation_angle_deg"] = _tag_float(esma[0], "ElevationAngle")
    return {k: v for k, v in out.items() if np.isfinite(v)}


def _elements(xml: str) -> tuple[list[str], list[float]]:
    syms: list[str] = []
    zs: list[float] = []
    for m in re.finditer(r'<ClassInstance[^>]*Type="TRTPSEElement"[^>]*>', xml):
        name = re.search(r'Name="([^"]+)"', m.group(0))
        if not name or name.group(1).strip() in syms:
            continue
        tail = xml[m.end() : m.end() + 60]
        z = re.search(r"<Element>\s*(\d+)", tail)
        syms.append(name.group(1).strip())
        zs.append(float(z.group(1)) if z else float("nan"))
    return syms, zs


def _sem_images(xml: str) -> list[np.ndarray]:
    out = []
    for block in _class_blocks(xml, "TRTImageData"):
        w = int(_tag_float(block, "Width") or 0)
        h = int(_tag_float(block, "Height") or 0)
        isz = int(_tag_float(block, "ItemSize") or 0)
        if w <= 0 or h <= 0 or isz <= 0:
            continue
        n_planes = int(_tag_float(block, "PlaneCount") or 1)
        for p in range(max(n_planes, 1)):
            plane = _tag_text(block, f"Plane{p}")
            b64 = _tag_text(plane, "Data").strip() if plane else ""
            if not b64:
                continue
            try:
                raw = base64.b64decode(b64)
            except Exception:
                continue
            need = w * h * isz
            if len(raw) < need:
                continue
            dt = {1: "u1", 2: "<u2"}.get(isz, "u1")
            n = w * h
            px = np.frombuffer(raw[: n * np.dtype(dt).itemsize], dtype=dt)
            out.append(px.reshape(h, w))
    return out


# ── assembly ─────────────────────────────────────────────────────────

def _energy_cal(calib_abs: float, calib_lin: float) -> AxisCal:
    if np.isfinite(calib_abs) and np.isfinite(calib_lin) and calib_lin != 0:
        return AxisCal(scale=calib_lin, origin=-calib_abs / calib_lin, units="keV")
    return AxisCal()


def _load_cube(
    sfs: SfsFile, n_chan: int, max_cube_bytes: float, metadata: dict[str, Any]
) -> np.ndarray | None:
    """Decode SpectrumData0 unless its dense size exceeds the guard."""
    sd = sfs.find("EDSDatabase/SpectrumData0")
    if sd is None or n_chan <= 0:
        return None
    raw = decompress_if_aacs(sfs.read(sd))
    if len(raw) < 8:
        return None
    h = int.from_bytes(raw[0:4], "little", signed=True)
    w = int.from_bytes(raw[4:8], "little", signed=True)
    est = h * w * n_chan * 4
    if 0 < est <= max_cube_bytes:
        return decode_cube(raw, n_chan)
    if est > 0:
        metadata["cube_skipped"] = (
            f"estimated {est / 1e9:.2f} GB ({h}x{w}x{n_chan}) exceeds "
            f"max_cube_bytes ({max_cube_bytes / 1e9:.2f} GB)"
        )
    return None


def load_bcf(
    path: str | Path,
    load_cube: bool = True,
    max_cube_bytes: float = 1.5e9,
) -> DataStruct:
    path = Path(path)
    sfs = SfsFile(path.read_bytes(), source=str(path))

    header = sfs.find("EDSDatabase/HeaderData")
    if header is None:
        raise ValueError(f"no EDSDatabase/HeaderData in {path}")
    xml = decompress_if_aacs(sfs.read(header)).decode("latin-1", errors="replace")

    spec = _class_blocks(xml, "TRTSpectrumHeader", first_only=True)
    calib_abs = _tag_float(spec[0], "CalibAbs") if spec else float("nan")
    calib_lin = _tag_float(spec[0], "CalibLin") if spec else float("nan")
    n_chan = int(_tag_float(xml, "ChCount") or 0)
    if n_chan <= 0:
        n_chan = 0

    sum_spec = np.array([])
    ch_text = _tag_text(xml, "Channels")
    if ch_text:
        sum_spec = np.array(
            [float(v) if v.strip() else 0.0 for v in ch_text.strip().split(",")]
        )
        n_chan = n_chan or sum_spec.size

    syms, zs = _elements(xml)
    images = _sem_images(xml)
    pixel_um = _sem_params(xml).get("pixel_size_um")
    spatial = AxisCal(scale=pixel_um, units="um") if pixel_um else AxisCal()

    metadata: dict[str, Any] = {
        "source": str(path),
        "parser": "bcf",
        "sem_params": _sem_params(xml),
        "elements": syms,
        "element_z": zs,
        "calib_abs": calib_abs,
        "calib_lin": calib_lin,
    }

    cube = _load_cube(sfs, n_chan, max_cube_bytes, metadata) if load_cube else None

    if cube is not None:
        # cube column-sum supersedes the (often truncated) header spectrum
        if images:
            metadata["sem_image"] = images[0]
        return DataStruct(
            data=cube,
            kind=DataKind.SPECTRUM_IMAGE,
            axes=(spatial, spatial, _energy_cal(calib_abs, calib_lin)),
            metadata=metadata,
        )

    if sum_spec.size:
        metadata["sum_spectrum"] = sum_spec
        metadata["energy_axis"] = _energy_cal(calib_abs, calib_lin).axis(sum_spec.size)
        metadata["n_channels"] = n_chan
    if images:
        return DataStruct(
            data=images[0], kind=DataKind.IMAGE,
            axes=(spatial, spatial), metadata=metadata,
        )
    if sum_spec.size:
        return DataStruct(
            data=sum_spec, kind=DataKind.SPECTRUM,
            axes=(_energy_cal(calib_abs, calib_lin),), metadata=metadata,
        )
    raise ValueError(f"no SEM image and no EDS spectrum found in {path}")
