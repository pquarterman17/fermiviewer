"""EMD (Electron Microscopy Dataset) reader — Data-Formats #2.

EMD is an HDF5 container with two common flavors, both handled here:

- **Velox** (Thermo/FEI ``.emd``): datasets live under
  ``/Data/Image/<uid>/Data`` (shaped ``[H, W, frames]``) with a per-dataset
  JSON ``Metadata`` blob carrying pixel size + acquisition settings. EDS data
  lives under ``/Data/SpectrumStream`` as a sparse event stream (not decoded
  here — a clear error points at that).
- **NCEM / Berkeley EMD v0.2** (vendor-neutral ``.emd``): a group tagged
  ``emd_group_type`` holds a ``data`` array plus ``dim1..dimN`` axis datasets
  (each with ``name``/``units`` attrs). Dense SI cubes load fully.

Returns a canonical ``DataStruct`` (IMAGE / SPECTRUM / SPECTRUM_IMAGE). 4D
data raises a clear "use the 4D pipeline" error (see plans/PLAN_4DSTEM.md);
nothing is flattened. Pure ``io/`` layer (h5py/numpy/stdlib only).
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.hdf5_common import (
    attr_str,
    axiscal_from_offset_scale,
    is_hdf5,
)

__all__ = ["EMDFormatError", "load_emd"]

ENERGY_UNITS = {"ev", "kev", "mev"}


class EMDFormatError(ValueError):
    """Raised for unreadable / non-EMD / unsupported-layout EMD files."""


def _is_energy(units: str) -> bool:
    return units.strip().lower() in ENERGY_UNITS


def _no_4d(shape: tuple[int, ...], path: Path) -> None:
    if len(shape) >= 4:
        raise EMDFormatError(
            f"{path.name} holds a {len(shape)}-D dataset {shape} — 4D-STEM is "
            f"not supported by the 3D pipeline (see PLAN_4DSTEM)."
        )


# ════════════════════════════════════════════════════════════════════
#  NCEM / Berkeley EMD v0.2
# ════════════════════════════════════════════════════════════════════

def _find_ncem_group(f: h5py.File) -> h5py.Group | None:
    """First group carrying the ``emd_group_type`` marker with a ``data``
    dataset — the NCEM emd container. Searches recursively."""
    found: list[h5py.Group] = []

    def visit(name: str, obj: h5py.HLObject) -> None:
        if (
            isinstance(obj, h5py.Group)
            and "emd_group_type" in obj.attrs
            and "data" in obj
            and isinstance(obj["data"], h5py.Dataset)
        ):
            found.append(obj)

    f.visititems(visit)
    return found[0] if found else None


def _ncem_axis(grp: h5py.Group, d: int, n: int) -> tuple[AxisCal, bool]:
    """AxisCal for NCEM ``dim<d>`` (1-based). Scale/offset come from the
    sample spacing of the dim array; name/units from its attrs."""
    key = f"dim{d}"
    if key not in grp:
        return AxisCal(), False
    ds = grp[key]
    units = attr_str(ds, "units")
    vals = np.asarray(ds[()], dtype=np.float64).ravel()
    if vals.size >= 2:
        scale = float(vals[1] - vals[0])
        offset = float(vals[0])
    elif vals.size == 1:
        scale, offset = 1.0, float(vals[0])
    else:
        scale, offset = 1.0, 0.0
    return axiscal_from_offset_scale(offset, scale, units), _is_energy(units)


def _load_ncem(grp: h5py.Group, path: Path) -> DataStruct:
    data = np.asarray(grp["data"][()])
    _no_4d(data.shape, path)
    ndim = data.ndim
    axes_info = [_ncem_axis(grp, d + 1, data.shape[d]) for d in range(ndim)]
    meta: dict[str, Any] = {
        "source": str(path),
        "parser": "emd",
        "emd_flavor": "ncem",
        "emd_group_type": int(np.asarray(grp.attrs["emd_group_type"]).ravel()[0]),
    }

    if ndim == 1:
        return DataStruct(
            data=data.astype(np.float64, copy=False),
            kind=DataKind.SPECTRUM,
            axes=(axes_info[0][0],),
            metadata=meta,
        )
    if ndim == 2:
        return DataStruct(
            data=data,
            kind=DataKind.IMAGE,
            axes=(axes_info[0][0], axes_info[1][0]),  # (y, x)
            metadata=meta,
        )
    # 3D: move the energy axis last (units-detected, else keep order). NCEM
    # data is C-ordered, so the lower-index spatial axis is y (not x).
    e_dim = next((d for d in range(3) if axes_info[d][1]), 2)
    y_dim, x_dim = sorted(set(range(3)) - {e_dim})
    cube = np.ascontiguousarray(np.moveaxis(data, (y_dim, x_dim, e_dim), (0, 1, 2)))
    return DataStruct(
        data=cube,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(axes_info[y_dim][0], axes_info[x_dim][0], axes_info[e_dim][0]),
        metadata=meta,
    )


# ════════════════════════════════════════════════════════════════════
#  Velox (Thermo/FEI)
# ════════════════════════════════════════════════════════════════════

def _velox_metadata_json(node: h5py.Group) -> dict[str, Any]:
    """Decode a Velox per-dataset ``Metadata`` blob (uint8 JSON, one column
    per frame) into a dict. Returns {} when absent/unparseable."""
    if "Metadata" not in node:
        return {}
    raw = np.asarray(node["Metadata"][()])
    if raw.ndim == 2:  # (bytes, frames) — first frame's metadata
        raw = raw[:, 0]
    try:
        text = raw.astype(np.uint8).tobytes().split(b"\x00", 1)[0]
        result: dict[str, Any] = json.loads(text.decode("utf-8", "replace"))
        return result
    except (ValueError, UnicodeDecodeError):
        return {}


def _velox_pixel_axes(md: dict[str, Any]) -> tuple[AxisCal, AxisCal]:
    """(y, x) AxisCals from a Velox metadata dict's BinaryResult.PixelSize.
    Velox stores metres; converted to nm for readability."""
    br = md.get("BinaryResult", {})
    psize = br.get("PixelSize", {})

    def cal(axis: str) -> AxisCal:
        try:
            scale = float(psize.get(axis, "nan"))
        except (TypeError, ValueError):
            return AxisCal()
        unit = str(br.get(f"PixelUnit{axis[0].upper()}", "m"))
        if not np.isfinite(scale) or scale == 0:
            return AxisCal()
        if unit == "m":  # metres → nm
            scale *= 1e9
            unit = "nm"
        return AxisCal(scale=scale, origin=0.0, units=unit)

    return cal("height"), cal("width")


def _pick_velox_image(images: h5py.Group) -> tuple[str, h5py.Group] | None:
    """The image sub-group with the largest Data array (skips thumbnails)."""
    best: tuple[str, h5py.Group] | None = None
    best_size = -1
    for key in images:
        node = images[key]
        if not isinstance(node, h5py.Group) or "Data" not in node:
            continue
        size = node["Data"].size
        if size > best_size:
            best_size = size
            best = (key, node)
    return best


def _load_velox(f: h5py.File, path: Path) -> DataStruct:
    data_grp = f["Data"]
    if "Image" not in data_grp:
        raise EMDFormatError(
            f"{path.name}: Velox EMD without an /Data/Image group — EDS "
            f"SpectrumStream import is not yet supported."
        )
    picked = _pick_velox_image(data_grp["Image"])
    if picked is None:
        raise EMDFormatError(f"{path.name}: no readable image under /Data/Image")
    key, node = picked
    raw = np.asarray(node["Data"][()])
    _no_4d(raw.shape, path)

    md = _velox_metadata_json(node)
    y_cal, x_cal = _velox_pixel_axes(md)
    meta: dict[str, Any] = {
        "source": str(path),
        "parser": "emd",
        "emd_flavor": "velox",
        "velox_uid": key,
        "image_tags": _flatten_velox_meta(md),
    }

    # Velox image data is [H, W, frames]; take the first frame (record count)
    if raw.ndim == 3:
        meta["n_frames"] = int(raw.shape[2])
        if raw.shape[2] > 1:
            import warnings

            warnings.warn(
                f"{path.name}: Velox EMD holds {raw.shape[2]} image frames; only "
                "the first is returned (image stacks are not supported).",
                stacklevel=2,
            )
        img = raw[:, :, 0]
    elif raw.ndim == 2:
        img = raw
    else:
        raise EMDFormatError(
            f"{path.name}: unexpected Velox image rank {raw.ndim} {raw.shape}"
        )
    return DataStruct(
        data=np.ascontiguousarray(img),
        kind=DataKind.IMAGE,
        axes=(y_cal, x_cal),
        metadata=meta,
    )


def _flatten_velox_meta(md: dict[str, Any]) -> dict[str, Any]:
    """Flatten a couple of useful Velox metadata branches to scalar leaves
    for the inspector (HT, detector, dwell), dotted-key style like dm.py."""
    out: dict[str, Any] = {}

    def walk(prefix: str, obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(f"{prefix}.{k}" if prefix else k, v)
        elif isinstance(obj, (int, float, str)):
            out[prefix] = obj

    for branch in ("Optics", "Detectors", "Acquisition", "BinaryResult"):
        if branch in md:
            walk(branch, md[branch])
    return out


# ════════════════════════════════════════════════════════════════════
#  Entry point
# ════════════════════════════════════════════════════════════════════

def load_emd(path: str | Path) -> DataStruct:
    """Parse a Velox or NCEM ``.emd`` file into a ``DataStruct``."""
    path = Path(path)
    with open(path, "rb") as fh:
        if not is_hdf5(fh.read(8)):
            raise EMDFormatError(f"not an HDF5/EMD file: {path}")

    with h5py.File(path, "r") as f:
        # Velox is recognised by its /Data/Image|Spectrum tree; NCEM by the
        # emd_group_type marker. Try Velox first (more specific structure).
        if "Data" in f and isinstance(f["Data"], h5py.Group):
            sub = set(f["Data"])
            if {"Image", "Spectrum", "SpectrumStream", "Line"} & sub:
                return _load_velox(f, path)
        ncem = _find_ncem_group(f)
        if ncem is not None:
            return _load_ncem(ncem, path)

    warnings.warn(
        f"{path.name}: no Velox or NCEM EMD structure found", stacklevel=2
    )
    raise EMDFormatError(
        f"{path.name}: unrecognised EMD layout (no /Data/Image or "
        f"emd_group_type group)"
    )
