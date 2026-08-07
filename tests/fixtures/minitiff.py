"""Synthetic vendor-tagged TIFF writers (FEI/Thermo Fisher, Zeiss, ImageJ).

The corpus has exactly one .tif — an ImageJ export — and no SEM/FIB file at
all, so the tag layouts `io.tiff_meta` reads had no CI-runnable coverage.
These builders write the private tags byte-for-byte the way the instruments
do (FEI: an INI blob in 34682/34680 with metres and radians; Zeiss: the
CZ_SEM key/value text in 34118), so the readers are exercised without
shipping instrument files.

The INI section/key names and units mirror a Helios NanoLab dual-beam
export: `[Scan] PixelWidth`/`PixelHeight` in metres, `[Stage] StageT` in
radians, `[Beam] Beam` naming the active column.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["fei_ini", "write_cz_sem_tiff", "write_fei_tiff", "write_imagej_tiff"]

TAG_CZ_SEM = 34118
TAG_FEI_SFEG = 34680
TAG_FEI_HELIOS = 34682


def fei_ini(sections: dict[str, dict[str, Any]]) -> str:
    """`{section: {key: value}}` → the CRLF INI text FEI writes into the tag."""
    lines: list[str] = []
    for name, body in sections.items():
        lines.append(f"[{name}]")
        lines.extend(f"{k}={v}" for k, v in body.items())
    return "\r\n".join(lines) + "\r\n"


def fei_sections(
    *,
    beam: str = "IBeam",
    pixel_m: float | None = 3.4e-9,
    tilt_rad: float | None = 0.9075712110370513,  # 52°, the FIB lift-out tilt
    hv: float = 30000.0,
    resolution: tuple[int, int] = (1536, 1024),
    databar_height: int = 79,
    hor_field_m: float | None = None,
) -> dict[str, dict[str, Any]]:
    """A Helios-shaped section map. `None` drops a value's whole block, so a
    caller can build the "field width only" and "no stage" variants."""
    scan: dict[str, Any] = {"InternalScan": "true", "Dwelltime": 1e-06}
    if pixel_m is not None:
        scan["PixelWidth"] = pixel_m
        scan["PixelHeight"] = pixel_m
    if hor_field_m is not None:
        scan["HorFieldsize"] = hor_field_m
        scan["VerFieldsize"] = hor_field_m * resolution[1] / resolution[0]

    sections: dict[str, dict[str, Any]] = {
        "User": {"Date": "05/07/2026", "Time": "03:04:59 PM", "User": "supervisor"},
        "System": {
            "Type": "DualBeam",
            "Software": "16.1.2",
            "Source": "FEG",
            "SystemType": "Helios NanoLab 660",
        },
        "Beam": {"HV": hv, "Spot": 3.0, "ScanRotation": 0.0, "Beam": beam},
        beam: {
            "Source": "FEG" if beam == "EBeam" else "LMIS",
            "HV": hv,
            "WD": 0.004,
            "BeamCurrent": 8e-11,
            "ScanRotation": 0.0,
            "StageX": -0.000123,
            "StageY": 0.000456,
            "StageZ": 0.004,
            "StageR": 0.5,
        },
        "Scan": scan,
        ("IScan" if beam == "IBeam" else "EScan"): dict(scan),
        "Image": {
            "DigitalContrast": 1.0,
            "ResolutionX": resolution[0],
            "ResolutionY": resolution[1],
        },
        "Detectors": {"Number": 1, "Name": "ETD"},
        "PrivateFei": {"BitShift": 0, "DatabarHeight": databar_height},
    }
    if tilt_rad is not None:
        sections["Stage"] = {
            "StageX": -0.000123,
            "StageY": 0.000456,
            "StageZ": 0.004,
            "StageR": 0.5,
            "StageT": tilt_rad,
            "StageTb": 0.0,
            "WorkingDistance": 0.004,
        }
        sections[beam]["StageTa"] = tilt_rad
    return sections


def write_fei_tiff(
    path: str | Path,
    data: np.ndarray,
    *,
    sections: dict[str, dict[str, Any]] | None = None,
    tag: int = TAG_FEI_HELIOS,
    **kwargs: Any,
) -> Path:
    """Write `data` as a TIFF carrying an FEI INI blob in `tag`.

    Extra keyword arguments are forwarded to `fei_sections`; pass an explicit
    `sections=` to control the layout completely (e.g. to omit `[Scan]`).
    """
    import tifffile

    if sections is None:
        sections = fei_sections(**kwargs)
    out = Path(path)
    tifffile.imwrite(
        out,
        np.asarray(data),
        photometric="minisblack",
        extratags=[(tag, 2, 0, fei_ini(sections), True)],  # 2 = ASCII
    )
    return out


def cz_sem_text(entries: dict[str, tuple[str, Any]]) -> str:
    """`{key: (label, value)}` → the SmartSEM CZ_SEM block layout: an
    UPPERCASE key line followed by a ``Label = value`` line."""
    lines: list[str] = []
    for key, (label, value) in entries.items():
        lines.append(key.upper())
        lines.append(f"{label} = {value}")
    return "\n".join(lines) + "\n"


def write_cz_sem_tiff(
    path: str | Path,
    data: np.ndarray,
    *,
    pixel: str = "3.400 nm",
    tilt_deg: str = "52.0 °",
    kv: str = "5.00 kV",
    extra: dict[str, tuple[str, Any]] | None = None,
) -> Path:
    """Write `data` as a Zeiss SmartSEM-tagged TIFF (tag 34118)."""
    import tifffile

    entries: dict[str, tuple[str, Any]] = {
        "ap_image_pixel_size": ("Image Pixel Size", pixel),
        "ap_stage_at_t": ("Stage at T", tilt_deg),
        "ap_actualkv": ("EHT Target Value", kv),
        "ap_wd": ("WD", "5.000 mm"),
        "ap_mag": ("Mag", "50.00 K X"),
        "sv_serial_number": ("Serial Number", "GEMINI-0001"),
        **(extra or {}),
    }
    # BYTE, not ASCII: SmartSEM writes the degree sign as the raw cp1252
    # byte 0xB0, which a 7-bit ASCII TIFF string cannot hold. tifffile's
    # CZ_SEM reader decodes UTF-8 with a cp1252 fallback, so this is the
    # byte sequence a real Gemini/Sigma export hands the parser.
    blob = cz_sem_text(entries).encode("cp1252")
    out = Path(path)
    tifffile.imwrite(
        out,
        np.asarray(data),
        photometric="minisblack",
        extratags=[(TAG_CZ_SEM, 1, len(blob), blob, True)],
    )
    return out


def write_imagej_tiff(
    path: str | Path,
    data: np.ndarray,
    *,
    unit: str = "nm",
    pixels_per_unit: float = 1.102271,
) -> Path:
    """Write an ImageJ-style TIFF: `unit=` in the description, pixel spacing
    in XResolution/YResolution (the shape a DM image exported via Fiji has)."""
    import tifffile

    out = Path(path)
    tifffile.imwrite(
        out,
        np.asarray(data),
        photometric="minisblack",
        imagej=True,
        resolution=(pixels_per_unit, pixels_per_unit),
        metadata={"unit": unit},
    )
    return out
