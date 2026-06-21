"""Minimal in-house CIF reader → ``Phase`` — Diffraction #2.

Parses the crystallographic core dictionary needed to build a fermiviewer
``Phase`` from a ``.cif`` file: cell lengths/angles, the space-group symbol
(for the Bravais centering), and the ``_atom_site`` loop (element + fractional
xyz + occupancy + B_iso). The centering letter slots straight into the existing
``_allowed`` / ``_simulate_extinct`` machinery — crucially preserving the
R-centering OBVERSE rule.

LIMITATION (documented, by design): the basis is built from the LISTED
``_atom_site`` rows only (P1 / "trust the listed sites") — full space-group
symmetry expansion is NOT applied. CIFs that list only the asymmetric unit will
yield a partial basis; most EM-reference CIFs list the full cell. A `gemmi`
(MPL-2.0) upgrade is the fallback if real-world CIF variety needs symmetry
expansion (noted in plans/PLAN_DIFFRACTION.md).

Pure layer: numpy/stdlib only. Apache-clean (no CIF library dep).
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from fermiviewer.calc.crystal import Basis, Phase

__all__ = ["CIFParseError", "load_cif", "parse_cif"]

_CENTERINGS = {"P", "I", "F", "A", "B", "C", "R", "H"}


class CIFParseError(ValueError):
    """Raised for unreadable / structurally invalid CIF content."""


def _strip_uncertainty(value: str) -> str:
    """Drop a trailing CIF standard-uncertainty like ``5.4309(5)`` → ``5.4309``."""
    return re.sub(r"\(\d+\)", "", value).strip()


def _num(value: str) -> float:
    try:
        return float(_strip_uncertainty(value))
    except ValueError as e:
        raise CIFParseError(f"non-numeric CIF value {value!r}") from e


def _element(token: str) -> str:
    """Element symbol from a type-symbol (``Si4+``, ``O2-``) or label (``Si1``):
    the leading run of letters, normalised to Xx capitalisation."""
    m = re.match(r"([A-Za-z]{1,2})", token.strip())
    if not m:
        raise CIFParseError(f"no element in atom-site token {token!r}")
    sym = m.group(1)
    return sym[0].upper() + sym[1:].lower()


def _tokenize(text: str) -> list[str]:
    """Quote-aware whitespace tokenizer. Skips ``#`` comment lines and ``;``
    multiline text blocks (not needed for the cell/atom-site core)."""
    tokens: list[str] = []
    in_block = False
    for line in text.splitlines():
        if line.startswith(";"):
            in_block = not in_block
            continue
        if in_block:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens.extend(shlex.split(stripped, comments=False))
        except ValueError:
            tokens.extend(stripped.split())  # unbalanced quotes → best effort
    return tokens


def _parse_tokens(
    tokens: list[str],
) -> tuple[dict[str, str], list[tuple[list[str], list[list[str]]]]]:
    """Split tokens into key→value pairs and (headers, rows) loop blocks."""
    data: dict[str, str] = {}
    loops: list[tuple[list[str], list[list[str]]]] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.lower() == "loop_":
            i += 1
            headers: list[str] = []
            while i < n and tokens[i].startswith("_"):
                headers.append(tokens[i].lower())
                i += 1
            values: list[str] = []
            while i < n and not (
                tokens[i].startswith("_")
                or tokens[i].lower() == "loop_"
                or tokens[i].lower().startswith("data_")
            ):
                values.append(tokens[i])
                i += 1
            ncol = len(headers)
            rows = [
                values[r : r + ncol]
                for r in range(0, len(values) - ncol + 1, ncol)
            ] if ncol else []
            loops.append((headers, rows))
        elif tok.startswith("_"):
            if i + 1 < n and not tokens[i + 1].startswith("_"):
                data[tok.lower()] = tokens[i + 1]
                i += 2
            else:
                i += 1
        else:
            i += 1
    return data, loops


def _centering(data: dict[str, str]) -> str:
    for key in (
        "_symmetry_space_group_name_h-m",
        "_space_group_name_h-m_alt",
        "_space_group_name_h-m_full",
    ):
        sym = data.get(key, "").strip().strip("'\"")
        if sym:
            letter = sym[0].upper()
            if letter in _CENTERINGS:
                return "P" if letter == "H" else letter  # H setting → P lattice
    return "P"  # default when no symbol present


def _system(a: float, b: float, c: float, al: float, be: float, ga: float) -> str:
    eq = lambda x, y: abs(x - y) < 1e-3  # noqa: E731
    ortho = eq(al, 90) and eq(be, 90) and eq(ga, 90)
    if ortho and eq(a, b) and eq(b, c):
        return "cubic"
    if ortho and eq(a, b):
        return "tetragonal"
    if ortho:
        return "orthorhombic"
    if eq(al, 90) and eq(be, 90) and eq(ga, 120) and eq(a, b):
        return "hexagonal"
    if eq(a, b) and eq(b, c) and eq(al, be) and eq(be, ga):
        return "rhombohedral"
    if eq(al, 90) and eq(ga, 90):
        return "monoclinic"
    return "triclinic"


def _basis(loops: list[tuple[list[str], list[list[str]]]]) -> Basis:
    """Build the basis from the atom-site loop (listed sites; no symmetry
    expansion). Empty when no fract coords are present."""
    for headers, rows in loops:
        if "_atom_site_fract_x" not in headers:
            continue
        col = {h: idx for idx, h in enumerate(headers)}
        sym_key = (
            "_atom_site_type_symbol"
            if "_atom_site_type_symbol" in col
            else "_atom_site_label"
        )
        out: list[tuple[str, float, float, float]] = []
        for row in rows:
            if len(row) < len(headers):
                continue
            out.append((
                _element(row[col[sym_key]]),
                _num(row[col["_atom_site_fract_x"]]),
                _num(row[col["_atom_site_fract_y"]]),
                _num(row[col["_atom_site_fract_z"]]),
            ))
        return tuple(out)
    return ()


def parse_cif(text: str, name: str = "", category: str = "custom") -> Phase:
    """Parse CIF text into a ``Phase``. ``name`` defaults to the CIF data block
    chemical name / formula when present."""
    tokens = _tokenize(text)
    if not tokens:
        raise CIFParseError("empty CIF")
    data, loops = _parse_tokens(tokens)
    try:
        a = _num(data["_cell_length_a"])
        b = _num(data["_cell_length_b"])
        c = _num(data["_cell_length_c"])
        alpha = _num(data["_cell_angle_alpha"])
        beta = _num(data["_cell_angle_beta"])
        gamma = _num(data["_cell_angle_gamma"])
    except KeyError as e:
        raise CIFParseError(f"missing required cell parameter {e}") from None

    formula = (
        data.get("_chemical_formula_sum")
        or data.get("_chemical_formula_structural")
        or ""
    ).strip().strip("'\"")
    display = (
        name
        or data.get("_chemical_name_mineral", "").strip().strip("'\"")
        or formula
        or "custom phase"
    )
    return Phase(
        name=display,
        formula=formula,
        a=a,
        b=b,
        c=c,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        centering=_centering(data),
        system=_system(a, b, c, alpha, beta, gamma),
        category=category,
        icsd=0,
        basis=_basis(loops),
    )


def load_cif(path: str | Path, category: str = "custom") -> Phase:
    """Read a ``.cif`` file into a ``Phase``."""
    path = Path(path)
    return parse_cif(path.read_text(encoding="utf-8", errors="replace"),
                     category=category)
