"""Bruker Nanoscope AFM parser (`.spm`, `.000`–`.nnn`).

Nanoscope files are an ASCII header (CIAO key/value sections, terminated by
Ctrl-Z) followed by one contiguous signed-integer block per channel. We
return a calibrated height image: lateral pitch (nm/px) in the axes and the
z-height scale + unit in metadata — for AFM the *pixel value itself* is the
physical height, not a separate axis.

Pure-library module: numpy + stdlib only (layering guard applies). The
calibration chain is the subtle part; see ``_z_scale`` for the two Bruker
conventions and which one applies.

Refs: Gwyddion ``nanoscope.c``; Bruker NanoScope header docs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct

__all__ = ["NanoscopeError", "is_nanoscope", "load_nanoscope", "load_nanoscope_all"]


class NanoscopeError(ValueError):
    """Unparseable / unsupported Nanoscope file (force curves, text mode…)."""


# Scan-size unit suffix → nanometres. `~m` is legacy NanoScope's 7-bit-safe
# spelling of µm (the µ byte is written as `~`); `um`/`µm` are the modern forms.
_UNIT_TO_NM = {"m": 1e9, "um": 1e3, "µm": 1e3, "~m": 1e3, "nm": 1.0, "pm": 1e-3}

# A CIAO "V"-type parameter line (leading backslash already stripped):
#   @[group:]Key: V [SoftScale] (HardScale units) HardValue units
_CIAO_V = re.compile(
    r"^@(?:\d+:)?(?P<key>.+?):\s+V"
    r"(?:\s+\[(?P<soft>[^\]]*)\])?"
    r"(?:\s+\((?P<hard>[^)]*)\))?"
    r"\s+(?P<value>.+)$"
)
_IMAGE_DATA = re.compile(r'^@(?:\d+:)?Image Data:\s+S\s+\[([^\]]*)\](?:\s+"([^"]*)")?')


class _Section(NamedTuple):
    name: str
    kv: dict[str, str]  # plain `\Key: value` pairs
    raw: list[str]  # every line in the section (sans leading backslash)


def is_nanoscope(buf: bytes) -> bool:
    """True if ``buf`` begins with the Nanoscope ``\\*File list`` signature
    (also accepts the rare ``?*`` text-mode opener and force files, which
    ``load_nanoscope`` then rejects with a clear message)."""
    if len(buf) < 12 or buf[0:1] not in (b"\\", b"?") or buf[1:2] != b"*":
        return False
    return buf[2:11] == b"File list" or buf[2:17] == b"Force file list"


def _split_header(buf: bytes) -> str:
    """Header text up to the Ctrl-Z terminator (or ``\\*File list end``)."""
    end = buf.find(b"\x1a")
    if end == -1:
        marker = buf.find(b"\\*File list end")
        end = marker if marker != -1 else min(len(buf), 1 << 18)
    return buf[:end].decode("latin-1", errors="replace")


def _parse_sections(text: str) -> list[_Section]:
    sections: list[_Section] = []
    cur: _Section | None = None
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line.startswith("\\"):
            continue
        body = line[1:]
        if body.startswith("*"):
            if cur is not None:
                sections.append(cur)
            cur = _Section(body[1:].strip(), {}, [])
        elif cur is not None:
            cur.raw.append(body)
            if not body.startswith("@") and ":" in body:
                key, _, val = body.partition(":")
                cur.kv[key.strip()] = val.strip()
    if cur is not None:
        sections.append(cur)
    return sections


def _lead_float(s: str) -> float:
    """First float token of e.g. ``430 nm/V`` → 430.0."""
    return float(s.strip().split()[0])


def _unit_numerator(s: str) -> str:
    """Unit of a sensitivity value, numerator only: ``100 nm/V`` → ``nm``."""
    toks = s.strip().split()
    return toks[1].split("/")[0] if len(toks) > 1 else "nm"


def _ciao_sensitivities(sections: list[_Section]) -> dict[str, tuple[float, str]]:
    """Map every CIAO soft-scale key (e.g. ``Sens. Zsens``) → (value, unit)."""
    out: dict[str, tuple[float, str]] = {}
    for sec in sections:
        for body in sec.raw:
            if not body.startswith("@"):
                continue
            m = _CIAO_V.match(body)
            if m and m["value"]:
                try:
                    out[m["key"].strip()] = (
                        _lead_float(m["value"]),
                        _unit_numerator(m["value"]),
                    )
                except (ValueError, IndexError):
                    continue
    return out


def _kv_ci(kv: dict[str, str], *keys: str) -> str:
    """First value whose key matches one of ``keys`` case-insensitively.

    Legacy NanoScope headers spell it ``Scan size`` where modern ones use
    ``Scan Size``; a case-insensitive lookup reads both.
    """
    lower = {k.lower(): v for k, v in kv.items()}
    for k in keys:
        if k.lower() in lower:
            return lower[k.lower()]
    return ""


def _scan_size_nm(scan: _Section) -> tuple[float, float]:
    """(x, y) physical extent in nm from ``\\Scan Size: 5e-006 5e-006 m``."""
    raw = _kv_ci(scan.kv, "Scan Size")
    toks = raw.split()
    nums = [t for t in toks if _is_num(t)]
    unit = next((t for t in reversed(toks) if not _is_num(t)), "m")
    factor = _UNIT_TO_NM.get(unit.lower(), 1.0)
    if not nums:
        raise NanoscopeError(f"unparseable Scan Size: {raw!r}")
    x = float(nums[0]) * factor
    y = float(nums[1]) * factor if len(nums) > 1 else x
    return x, y


def _is_num(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


_ZSCALE_LINE = re.compile(r"^@(?:\d+:)?Z scale:")
_NUM = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
_SOFT = re.compile(r"\[([^\]]*)\]")
# first number inside the hard-scale parenthetical (units may themselves
# contain parens, e.g. "log(Arb)/LSB", so match the number, not the whole ())
_HARD = re.compile(r"\(\s*(" + _NUM + r")")
# the hard-scale unit is the token(s) between that number and `/LSB`
# — e.g. "(… Arb/LSB)" → Arb, "(… log(Arb)/LSB)" → log(Arb). This is the
# authoritative channel unit; the sensitivity line often carries a bogus
# "nm" placeholder for non-length channels (modulus, dissipation).
_HARD_UNIT = re.compile(r"\(\s*" + _NUM + r"\s+(?P<unit>.+?)\s*/\s*LSB\b")
# the trailing hard value: the number after the parenthetical's close paren
_VALUE = re.compile(r"\)\s+(" + _NUM + r")")


def _z_scale(
    image: _Section, sens: dict[str, tuple[float, str]], bpp: int
) -> tuple[float, str]:
    """Physical nm (or °, …) per raw LSB for a channel, plus its unit.

    Bruker carries the z-scale as a CIAO line, e.g.::

        \\@2:Z scale: V [Sens. Zsens] (0.006714 V/LSB) 440.0 V

    The soft-scale name in brackets points at a sensitivity in another
    section. Two conventions coexist:

    * **Method A** (modern, preferred when the parenthetical hard-scale is
      present): ``z = raw · hard_scale · sensitivity`` — the hard-scale is
      already volts-per-LSB and encodes the bit depth, so no extra divisor.
    * **Method B** (legacy v5/v6): ``z = raw · (hard_value / 2^(8·bpp)) ·
      sensitivity`` — divide the full-scale hard value by the ADC range.

    The unit is taken from the hard-scale parenthetical (``Arb/LSB`` →
    ``Arb``). Only when that is a raw electrical unit (``V``/``LSB``) — as
    for a height channel measured in volts and converted by a nm/V
    sensitivity — does the sensitivity's own unit win.
    """
    line = next((b for b in image.raw if _ZSCALE_LINE.match(b)), None)
    if line is None:
        return 1.0, ""
    soft_m, hard_m, val_m = _SOFT.search(line), _HARD.search(line), _VALUE.search(line)
    soft = soft_m.group(1).strip() if soft_m else ""

    # A named soft-scale must resolve to *its own* sensitivity — never
    # borrow the height (Zsens) sensitivity for a different channel, which
    # would silently mis-scale it. Only an empty bracket falls back to the
    # generic Z keys.
    sensitivity, sens_unit = 1.0, ""
    for key in ([soft] if soft else ["Sens. Zsens", "Sens. Zscale", "Sensitivity"]):
        if key in sens:
            sensitivity, sens_unit = sens[key]
            break

    hu = _HARD_UNIT.search(line)
    hard_unit = hu.group("unit").strip() if hu else ""
    unit = hard_unit if hard_unit and hard_unit not in ("V", "LSB") else sens_unit

    hard_scale = float(hard_m.group(1)) if hard_m else 0.0
    if hard_scale:  # Method A
        return hard_scale * sensitivity, unit
    hard_value = float(val_m.group(1)) if val_m else 0.0  # Method B
    return hard_value / float(1 << (8 * bpp)) * sensitivity, unit


def _channel_name(image: _Section) -> str:
    for body in image.raw:
        m = _IMAGE_DATA.match(body)
        if m:
            return (m.group(1) or m.group(2) or "Image").strip()
    return "Image"


def _read_channel(
    buf: bytes, image: _Section, scan: _Section, sens: dict[str, tuple[float, str]]
) -> DataStruct:
    kv = image.kv
    try:
        offset = int(kv["Data offset"])
        bpp = int(kv.get("Bytes/pixel", "2"))
        nx = int(kv.get("Samps/line") or scan.kv["Samps/line"])
        ny = int(kv.get("Number of lines") or scan.kv.get("Lines") or scan.kv["Number of lines"])
    except (KeyError, ValueError) as e:
        raise NanoscopeError(f"missing image geometry: {e}") from None

    dtype = "<i4" if bpp == 4 else "<i2"
    if offset + nx * ny * bpp > len(buf):
        raise NanoscopeError("data block runs past end of file")
    raw = np.frombuffer(buf, dtype=dtype, count=nx * ny, offset=offset)
    rows = np.flipud(raw.reshape(ny, nx))  # stored bottom-to-top

    z_scale, z_unit = _z_scale(image, sens, bpp)
    data = np.ascontiguousarray(rows.astype(np.float64) * z_scale)

    x_nm, y_nm = _scan_size_nm(scan)
    axes = (
        AxisCal(scale=y_nm / ny, origin=0.0, units="nm"),
        AxisCal(scale=x_nm / nx, origin=0.0, units="nm"),
    )
    channel = _channel_name(image)
    return DataStruct(
        data=data,
        kind=DataKind.IMAGE,
        axes=axes,
        metadata={
            "parser": "nanoscope",
            "channel": channel,
            "value_unit": z_unit,  # surfaced on the z-colorbar
            "z_scale_per_lsb": z_scale,
            "scan_size_nm": [round(x_nm, 6), round(y_nm, 6)],
            "samps_per_line": nx,
            "num_lines": ny,
            "bytes_per_pixel": bpp,
        },
    )


def load_nanoscope_all(path: str | Path) -> list[DataStruct]:
    """Every image channel in the file as separate height images."""
    buf = Path(path).read_bytes()
    if not is_nanoscope(buf):
        raise NanoscopeError("not a Bruker Nanoscope file")
    if buf[2:17] == b"Force file list":
        raise NanoscopeError("force-curve files are not supported")
    if buf[0:1] == b"?":
        raise NanoscopeError("text-mode Nanoscope files are not supported")
    sections = _parse_sections(_split_header(buf))
    scan = next((s for s in sections if s.name == "Ciao scan list"), None)
    images = [s for s in sections if s.name == "Ciao image list"]
    if scan is None or not images:
        raise NanoscopeError("no Ciao scan/image list — unsupported Nanoscope variant")
    sens = _ciao_sensitivities(sections)
    return [_read_channel(buf, img, scan, sens) for img in images]


def load_nanoscope(path: str | Path) -> DataStruct:
    """The primary (Height/ZSensor) channel as a calibrated height image."""
    channels = load_nanoscope_all(path)
    for ds in channels:
        name = str(ds.metadata.get("channel", "")).lower()
        if "height" in name or "zsensor" in name or "z sensor" in name:
            return ds
    return channels[0]
