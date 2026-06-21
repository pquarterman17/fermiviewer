"""Minimal synthetic EMD writers (Velox + NCEM flavors) for parser tests.

h5py makes these tiny — no hand-rolled binary like minidm4. The real-data /
rosettasciio oracle paths cover the byte-exact contracts; these fixtures pin
the structural mapping (flavor detection, axis cal, energy-last reorder).
"""

from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

__all__ = ["write_ncem_emd", "write_velox_emd"]


def write_ncem_emd(
    path: Path,
    data: np.ndarray,
    dims: list[tuple[np.ndarray, str, str]],
) -> Path:
    """NCEM/Berkeley EMD v0.2: a group tagged emd_group_type with `data` and
    `dim1..dimN` axis datasets. `dims` is per-axis (values, name, units)."""
    with h5py.File(path, "w") as f:
        f.attrs["version_major"] = 0
        f.attrs["version_minor"] = 2
        grp = f.create_group("experiment/data")
        grp.attrs["emd_group_type"] = 1
        grp.create_dataset("data", data=data)
        for i, (vals, name, units) in enumerate(dims, start=1):
            d = grp.create_dataset(f"dim{i}", data=np.asarray(vals))
            d.attrs["name"] = name
            d.attrs["units"] = units
    return path


def write_velox_emd(
    path: Path,
    image_hwf: np.ndarray,
    pixel_size_m: float = 1e-10,
    metadata: dict | None = None,
) -> Path:
    """Velox EMD: /Data/Image/<uid>/{Data [H,W,frames], Metadata (uint8 JSON)}.
    pixel_size_m is metres per pixel (Velox convention)."""
    md = {
        "BinaryResult": {
            "PixelSize": {"width": str(pixel_size_m), "height": str(pixel_size_m)},
            "PixelUnitX": "m",
            "PixelUnitY": "m",
        },
        "Optics": {"AccelerationVoltage": "200000"},
    }
    if metadata:
        md.update(metadata)
    blob = np.frombuffer(json.dumps(md).encode("utf-8") + b"\x00", dtype=np.uint8)

    with h5py.File(path, "w") as f:
        node = f.create_group("Data/Image/0123abcd")
        node.create_dataset("Data", data=image_hwf)
        # Velox stores Metadata as (bytes, frames); one column per frame
        nf = image_hwf.shape[2] if image_hwf.ndim == 3 else 1
        meta_col = blob.reshape(-1, 1)
        node.create_dataset("Metadata", data=np.tile(meta_col, (1, nf)))
    return path
