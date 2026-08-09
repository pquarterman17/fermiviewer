"""Gatan DigitalMicrograph DM5 (GMS 3.5+ HDF5) parser — Data-Formats #3.

DM5 is GMS 3.5's HDF5 successor to the binary DM3/DM4 tag-tree format: the
same document model (``ImageList`` of image records, each with pixel data,
per-dimension calibration, and a nested acquisition-tag tree) is written out
as an HDF5 container of groups/attributes instead of packed binary tags.
This reader mirrors ``io/dm.py`` (the DM3/DM4 reader) as closely as the
container format allows, so a DM5 file and a DM3/DM4 file holding the same
acquisition produce IDENTICAL ``DataStruct``s: same calibration convention
``value = (index − origin) × scale``, energy axis LAST for spectral kinds,
same ``image_tags`` metadata-harvest shape.

Layout this reader consumes (root)::

    ImageList/<n>/ImageData/Data                          dataset
    ImageList/<n>/ImageData/Calibrations/Brightness        group, attrs Origin/Scale/Units
    ImageList/<n>/ImageData/Calibrations/Dimension/<d>     group, attrs Origin/Scale/Units
    ImageList/<n>/ImageTags/...                            nested groups + attrs
    ImageList/<n>/ImageDisplayInfo                         group, attrs LowLimit/HighLimit/
                                                            Gamma/IsInverted

No public DM5 sample file exists to validate this against (verified
2026-08-01 — GMS 3.5+ HDF5 exports are not in any of the public rsciio/
hyperspy example corpora or elsewhere online). This module is built from
Gatan's dm5-documentation page (https://www.gatan.com/dm5-documentation,
which documents the ``ImageList``/``ImageData``/``Calibrations``/
``ImageTags`` group paths and the ``Origin``/``Scale`` float32 calibration
pair above) plus the general HDF5-vs-DM dimension-order behaviour described
by the third-party niermann/gms_plugin_hdf5 project. Several structural
details are therefore ASSUMPTIONS, called out below; there is no
``@pytest.mark.realdata`` test for this reader for the same reason — add one
once a real ``.dm5`` corpus file becomes available, and revisit every
assumption against it first.

ASSUMPTIONS (not confirmed by Gatan's own documentation):

1. **Dimension order is DM-index-reversed relative to the HDF5 array axes**,
   the same way niermann/gms_plugin_hdf5 documents it: DigitalMicrograph
   indexes dimensions row-major/Fortran-style (dimension 0 fastest) while
   HDF5 stores datasets C-order (last axis fastest), so the plugin "reverses
   index order... DM's [X,Y,Z] indexing corresponds to HDF5's [Z,Y,X]". This
   is a property of the HDF5 C library's storage convention, not that
   specific plugin, so it is assumed to hold for GMS's own native DM5
   writer too. Concretely: DM dimension ``d`` calibrates HDF5/array axis
   ``(ndim − 1 − d)``. This lets the 3D spectrum-image tail below reuse
   ``io/dm.py``'s exact post-reshape transpose logic unchanged — the raw
   ``Data`` dataset here plays the same role as ``dm.py``'s
   ``arr = px.reshape(dims[2], dims[1], dims[0])``.
2. **Per-axis calibration is stored as HDF5 attributes**, not sub-datasets:
   ``Calibrations/Dimension/<d>`` is a group with ``Origin``/``Scale``/
   ``Units`` attributes (Gatan's docs confirm the Origin+Scale-as-float32
   pair but not the attribute-vs-dataset representation; attributes are the
   natural HDF5 idiom for scalar leaves, and niermann/gms_plugin_hdf5
   separately describes DM tag scalars round-tripping through HDF5 object
   attributes).
3. **``ImageTags`` metadata mirrors the DM tag tree as nested groups with
   scalar/string leaves stored as attributes** on the innermost group,
   analogous reasoning to #2. Harvested the same way ``dm.py`` harvests
   ``ImageList.<n>.ImageTags.*`` scalar/string tags into a flat dotted-key
   ``metadata["image_tags"]`` dict.
4. **Thumbnails do not appear inline in ``ImageList``.** Gatan's docs list a
   separate root-level ``Thumbnails`` group (unlike DM3/DM4, which inlines
   thumbnails into ``ImageList`` flagged by ``DataType`` 23), so no
   thumbnail-DataType skip is needed here. ``_pick_image`` still keeps
   ``dm.py``'s first-match / warn-on-extra / fallback-to-largest shape for
   behavioural parity, skipping only boolean-mask dtype entries (the DM5
   analogue of ``dm.py``'s ``BOOLEAN_DTYPE`` skip).
5. **Pixel dtype comes directly from the HDF5 dataset's native dtype** —
   unlike DM3/DM4's packed binary blob (which needs the ``DataType`` tag
   decoded via a lookup table), an HDF5 dataset is already natively typed,
   so no DM ``DataType``-code table is needed or read.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.hdf5_common import attr_float, attr_str, is_hdf5
from fermiviewer.io.metadata import stage_tilt_from_image_tags

__all__ = ["DM5FormatError", "load_dm5"]

MAX_DEPTH = 50
ENERGY_UNITS = {"ev", "kev", "mev"}


class DM5FormatError(ValueError):
    """Raised for unreadable / non-DM5 / structurally-unusable HDF5 files."""


# ════════════════════════════════════════════════════════════════════
#  Small HDF5 tree helpers
# ════════════════════════════════════════════════════════════════════

def _get_group(node: h5py.Group, path: str) -> h5py.Group | None:
    """Walk a '/'-separated relative path one level at a time (safer than
    relying on multi-segment ``in``/``[]`` support across h5py versions)."""
    cur: h5py.HLObject = node
    for part in path.split("/"):
        if not isinstance(cur, h5py.Group) or part not in cur:
            return None
        cur = cur[part]
    return cur if isinstance(cur, h5py.Group) else None


def _numeric_children(group: h5py.Group) -> list[tuple[int, h5py.Group]]:
    """Integer-keyed subgroups (e.g. ImageList's "0", "1", ...), sorted
    numerically — h5py's default iteration order is lexical, which would
    misorder "10" before "2"."""
    out: list[tuple[int, h5py.Group]] = []
    for key in group:
        try:
            idx = int(key)
        except ValueError:
            continue
        try:
            item = group[key]
        except (KeyError, OSError):
            continue  # dangling link
        if isinstance(item, h5py.Group):
            out.append((idx, item))
    return sorted(out, key=lambda t: t[0])


def _image_data_node(entry: h5py.Group) -> h5py.Dataset | None:
    image_data = _get_group(entry, "ImageData")
    if image_data is None:
        return None
    ds = image_data.get("Data")
    return ds if isinstance(ds, h5py.Dataset) else None


def _decode_value(v: Any) -> Any:
    """Decode an h5py attribute/scalar: bytes -> str, 0-d/1-elem arrays ->
    their scalar; anything else (including multi-element arrays) -> None."""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, np.ndarray):
        if v.shape == ():
            return _decode_value(v[()])
        if v.size == 1:
            return _decode_value(v.reshape(-1)[0])
        return None
    if isinstance(v, np.generic):
        return v.item()
    return v


# ════════════════════════════════════════════════════════════════════
#  Image selection (mirrors dm.py's _pick_image / _largest_image)
# ════════════════════════════════════════════════════════════════════

def _pick_image(
    image_list: h5py.Group, path: Path
) -> tuple[int, h5py.Group, h5py.Dataset]:
    first: tuple[int, h5py.Group, h5py.Dataset] | None = None
    extras: list[int] = []
    for idx, entry in _numeric_children(image_list):
        ds = _image_data_node(entry)
        if ds is None or ds.dtype.kind == "b":  # boolean mask — see ASSUMPTION 4
            continue
        if first is None:
            first = (idx, entry, ds)
        else:
            extras.append(idx)
    if first is not None:
        if extras:
            warnings.warn(
                f"DM5 file {path.name} has extra images at ImageList {extras} — "
                f"using ImageList.{first[0]}",
                stacklevel=3,
            )
        return first
    best = _largest_image(image_list)
    if best is None:
        raise DM5FormatError(f"no usable image in {path} (ImageList empty?)")
    return best


def _largest_image(
    image_list: h5py.Group,
) -> tuple[int, h5py.Group, h5py.Dataset] | None:
    """Fallback: ImageList entry with the largest pixel count."""
    best: tuple[int, h5py.Group, h5py.Dataset] | None = None
    best_px = -1
    for idx, entry in _numeric_children(image_list):
        ds = _image_data_node(entry)
        if ds is None:
            continue
        if ds.size > best_px:
            best_px, best = ds.size, (idx, entry, ds)
    return best


# ════════════════════════════════════════════════════════════════════
#  Calibration / metadata accessors
# ════════════════════════════════════════════════════════════════════

def _axis_cal(image_data: h5py.Group, d: int, default_units: str = "") -> AxisCal:
    node = _get_group(image_data, f"Calibrations/Dimension/{d}")
    if node is None:
        return AxisCal(scale=float("nan"), origin=0.0, units=default_units)
    return AxisCal(
        scale=attr_float(node, "Scale", float("nan")),
        origin=attr_float(node, "Origin", 0.0),
        units=attr_str(node, "Units", default_units),
    )


def _brightness_cal(image_data: h5py.Group) -> tuple[float, float, str]:
    node = _get_group(image_data, "Calibrations/Brightness")
    if node is None:
        return 0.0, 1.0, ""
    return (
        attr_float(node, "Origin", 0.0),
        attr_float(node, "Scale", 1.0),
        attr_str(node, "Units", ""),
    )


def _display_info(entry: h5py.Group) -> dict[str, Any]:
    node = entry.get("ImageDisplayInfo")
    if not isinstance(node, h5py.Group):
        return {
            "display_low": float("nan"),
            "display_high": float("nan"),
            "display_gamma": 1.0,
            "display_inverted": False,
        }
    return {
        "display_low": attr_float(node, "LowLimit", float("nan")),
        "display_high": attr_float(node, "HighLimit", float("nan")),
        "display_gamma": attr_float(node, "Gamma", 1.0),
        "display_inverted": bool(attr_float(node, "IsInverted", 0.0)),
    }


def _degenerate_spectrum_dim(image_data: h5py.Group, shape: tuple[int, ...]) -> int | None:
    """DM5 analogue of dm.py's `_degenerate_spectrum_dim`.

    `shape` is the array's (rows, cols); DM dimension 1 is the row axis and
    dimension 0 the column axis, so the DM index of the surviving axis is
    the opposite of the array axis being dropped.
    """
    if len(shape) != 2 or 1 not in shape:
        return None
    keep_dm = 0 if shape[0] == 1 else 1   # drop rows -> keep DM dim 0 (cols)
    keep_axis = 1 - keep_dm               # ...which is array axis 1
    if shape[keep_axis] <= 1:
        return None  # 1x1 — no axis worth keeping
    node = _get_group(image_data, f"Calibrations/Dimension/{keep_dm}")
    if node is None:
        return None
    units = attr_str(node, "Units", "").strip().lower()
    return keep_dm if units in ENERGY_UNITS else None


def _energy_dim(image_data: h5py.Group) -> int:
    for d in range(3):
        node = _get_group(image_data, f"Calibrations/Dimension/{d}")
        if node is None:
            continue
        if attr_str(node, "Units", "").strip().lower() in ENERGY_UNITS:
            return d
    return 2  # GMS layout default: energy last


def _harvest_image_tags(
    node: h5py.Group, prefix: str = "", depth: int = 0
) -> dict[str, Any]:
    """Flatten ImageTags into dotted-key scalars/strings — the DM5 analogue
    of dm.py's ImageTags harvest (see ASSUMPTION 3)."""
    out: dict[str, Any] = {}
    if depth > MAX_DEPTH:
        return out
    for k, v in node.attrs.items():
        val = _decode_value(v)
        if isinstance(val, (int, float, str)):
            out[f"{prefix}.{k}" if prefix else k] = val
    for key in node:
        try:
            item = node[key]
        except (KeyError, OSError):
            continue  # dangling link
        child_prefix = f"{prefix}.{key}" if prefix else key
        if isinstance(item, h5py.Group):
            out.update(_harvest_image_tags(item, child_prefix, depth + 1))
        elif isinstance(item, h5py.Dataset) and item.shape in ((), (1,)):
            val = _decode_value(item[()])
            if isinstance(val, (int, float, str)):
                out[child_prefix] = val
    return out


# ════════════════════════════════════════════════════════════════════
#  Entry point
# ════════════════════════════════════════════════════════════════════

def load_dm5(path: str | Path) -> DataStruct:
    """Parse a .dm5 (GMS 3.5+ HDF5) file into a DataStruct.

    See the module docstring for the documented + ASSUMED HDF5 layout —
    there is no public DM5 corpus file to validate this reader against.
    """
    path = Path(path)
    with open(path, "rb") as fh:
        if not is_hdf5(fh.read(8)):
            raise DM5FormatError(f"not an HDF5/DM5 file: {path}")

    with h5py.File(path, "r") as f:
        image_list = f.get("ImageList")
        if not isinstance(image_list, h5py.Group):
            raise DM5FormatError(f"{path.name}: no /ImageList group — not a DM5 file")

        idx, entry, ds = _pick_image(image_list, path)
        image_data = entry["ImageData"]
        arr = np.asarray(ds[()])
        ndim = arr.ndim

        if ndim == 0:
            raise DM5FormatError(f"{path.name}: 0-D dataset — no image/spectrum data")
        if ndim >= 4:
            raise DM5FormatError(
                f"{path.name}: {ndim}-D signal {arr.shape} — 4D-STEM is not "
                f"supported by the 3D pipeline (see PLAN_4DSTEM)."
            )

        b_origin, b_scale, b_units = _brightness_cal(image_data)
        metadata: dict[str, Any] = {
            "source": str(path),
            "parser": "dm5",
            "dm_version": 5,
            "dm5_dtype": str(ds.dtype),
            "bit_depth": ds.dtype.itemsize * 8,
            "intensity_origin": b_origin,
            "intensity_scale": b_scale,
            "intensity_units": b_units,
            **_display_info(entry),
        }
        tags_node = entry.get("ImageTags")
        metadata["image_tags"] = (
            _harvest_image_tags(tags_node) if isinstance(tags_node, h5py.Group) else {}
        )
        # Same dotted-leaf normalization as dm.py — DM5 keeps DM's tag names.
        tilt_deg = stage_tilt_from_image_tags(metadata["image_tags"])
        if np.isfinite(tilt_deg):
            metadata["stage_tilt_deg"] = tilt_deg

        if ndim == 1:                            # 1D spectrum
            return DataStruct(
                data=arr,
                kind=DataKind.SPECTRUM,
                axes=(_axis_cal(image_data, 0, "eV"),),
                metadata=metadata,
            )

        if ndim == 2:                            # 2D image (row-major: [H, W])
            spec_dim = _degenerate_spectrum_dim(image_data, arr.shape)
            if spec_dim is not None:             # 1xN / Nx1 energy axis
                metadata["squeezed_from_shape"] = list(arr.shape)
                return DataStruct(
                    data=arr.reshape(-1),
                    kind=DataKind.SPECTRUM,
                    axes=(_axis_cal(image_data, spec_dim, "eV"),),
                    metadata=metadata,
                )
            return DataStruct(
                data=arr,
                kind=DataKind.IMAGE,
                axes=(_axis_cal(image_data, 1), _axis_cal(image_data, 0)),
                metadata=metadata,
            )

        # 3D spectrum image: per ASSUMPTION 1, `arr` already holds the DM
        # dimension-reversed layout `dm.py` computes explicitly via
        # `px.reshape(dims[2], dims[1], dims[0])` — reuse its tail verbatim.
        e_dim = _energy_dim(image_data)
        x_dim, y_dim = sorted(set(range(3)) - {e_dim})  # faster spatial dim = x
        axis_of = [2, 1, 0]                              # dim id at each array axis
        cube = arr.transpose(
            axis_of.index(y_dim), axis_of.index(x_dim), axis_of.index(e_dim)
        )
        return DataStruct(
            data=np.ascontiguousarray(cube),
            kind=DataKind.SPECTRUM_IMAGE,
            axes=(
                _axis_cal(image_data, y_dim),
                _axis_cal(image_data, x_dim),
                _axis_cal(image_data, e_dim, "eV"),
            ),
            metadata=metadata,
        )
