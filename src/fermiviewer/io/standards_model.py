"""Known-composition standards (roadmap 5b, first box).

A STANDARD is a material whose composition is known independently of the
measurement -- a certified reference material, a well-characterised
alloy, a film of stated stoichiometry. It is the only thing that turns
EDS from a ratio into a quantity: the built-in Cliff-Lorimer table is one
instrument's 200 kV numbers, and an experimental factor set can only be
derived by measuring something whose answer you already know.

Deliberately built on ADR 0009's vocabulary rather than beside it.
`Quantity`, `Validity` and `Provenance` mean the same things here as on a
profile, and a second spelling of "a value with a unit and a sigma" is
how two readings of the same concept drift apart.

What a standard is NOT: a measurement. The composition is a property of
the material and travels with it; where and when it was measured are
`ReferenceRegion` entries, which name an image and a region reference and
are resolved only when a derivation actually reads them. A stale image id
is therefore an error at DERIVATION time, where the user can act on it,
not at storage time, where it would make a standard un-saveable because a
session was closed.

Pure layer, stdlib only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fermiviewer.io.profiles_model import (
    ProfileError,
    Provenance,
    Quantity,
    Validity,
    provenance_from,
    quantity_from,
    validity_from,
)

__all__ = [
    "COMPOSITION_BASES",
    "STANDARD_SCHEMA",
    "ReferenceRegion",
    "Standard",
    "StandardError",
    "composition_from",
    "normalized_fractions",
    "reference_region_from",
    "standard_from_json",
    "standard_to_json",
]

#: Revision of the per-standard shape (and of the store file), so a later
#: build can migrate one at a time. Same rule as `PROFILE_SCHEMA`.
STANDARD_SCHEMA = 1

#: A composition is stated in one of these. They are NOT interchangeable
#: without the atomic weights, so the basis is stored rather than assumed:
#: a certificate quoting 61.5 wt% Cu means something different from
#: 61.5 at% Cu, and guessing costs the whole point of using a standard.
COMPOSITION_BASES = ("wt", "at")


class StandardError(ValueError):
    """A standard that cannot be read or does not make sense."""


@dataclass(frozen=True)
class ReferenceRegion:
    """Where this standard was measured: an image and a region reference.

    `region` and `roi` are the frozen strings `region_resolve.resolve_region`
    already takes (``"set_id"`` / ``"set_id/region_id"``, and the 1-based
    inclusive ``"r1,c1,r2,c2"``), so a reference stored here resolves by
    the same rules as one typed into any other route. Both empty means the
    whole image.
    """

    label: str
    image_id: str = ""
    region: str = ""
    roi: str = ""
    note: str = ""


@dataclass(frozen=True)
class Standard:
    id: str
    name: str
    version: int
    created_at: str
    updated_at: str
    #: "wt" or "at" -- which basis `composition` is stated in
    basis: str
    #: element symbol -> fraction in PERCENT of `basis`, with its 1σ
    composition: dict[str, Quantity]
    #: optional bulk properties a derivation may need. `mass_thickness`
    #: is what a ζ derivation requires and a density+thickness pair
    #: cannot always supply (a wedge has neither at a given pixel).
    density: Quantity | None = None
    mass_thickness: Quantity | None = None
    thickness: Quantity | None = None
    text: dict[str, str] = field(default_factory=dict)
    regions: tuple[ReferenceRegion, ...] = ()
    validity: Validity = field(default_factory=Validity)
    provenance: Provenance = field(default_factory=Provenance)
    extra: dict[str, Any] = field(default_factory=dict)


#: Keys this build models; anything else on a stored standard is `extra`
#: and rides back out untouched (the ADR 0009 unknown-key rule).
_STANDARD_KEYS = frozenset(
    {
        "id",
        "schema",
        "name",
        "version",
        "created_at",
        "updated_at",
        "basis",
        "composition",
        "density",
        "mass_thickness",
        "thickness",
        "text",
        "regions",
        "validity",
        "provenance",
        "history",
    }
)

#: Canonical units for the optional bulk properties, enforced the way
#: `FIELD_UNITS` enforces a profile's -- a density quoted in kg/m³ where
#: every consumer reads g/cm³ is a 1000x error with a plausible number.
_BULK_UNITS = {
    "density": "g/cm3",
    "mass_thickness": "kg/m2",
    "thickness": "nm",
}



def composition_from(basis: Any, raw: Any) -> tuple[str, dict[str, Quantity]]:
    """Validate a composition mapping into ``(basis, {element: Quantity})``.

    Percentages, not fractions: a certificate states 61.5 wt%, and storing
    0.615 would invite exactly the factor-of-100 this validation exists to
    catch. Each entry must be positive -- an element present at 0% is an
    element the standard does not contain, and listing it would put a zero
    in a ratio.
    """
    if basis not in COMPOSITION_BASES:
        raise StandardError(
            f"composition basis must be one of {list(COMPOSITION_BASES)}, got {basis!r}"
        )
    if not isinstance(raw, Mapping) or not raw:
        raise StandardError("a standard needs a composition of at least one element")
    out: dict[str, Quantity] = {}
    for symbol, value in raw.items():
        if not isinstance(symbol, str) or not symbol.strip():
            raise StandardError("composition keys must be element symbols")
        try:
            q = quantity_from(symbol, value, "%")
        except ProfileError as exc:
            raise StandardError(str(exc)) from None
        if q.unit != "%":
            raise StandardError(
                f"composition of {symbol!r} must be in '%' ({basis}%), got {q.unit!r}"
            )
        if q.value <= 0:
            raise StandardError(
                f"composition of {symbol!r} must be > 0 -- an element at 0% is one "
                "the standard does not contain"
            )
        out[symbol.strip()] = q
    total = sum(q.value for q in out.values())
    if total > 100.0 + 1e-6:
        raise StandardError(
            f"composition sums to {total:g}%, which is more than the whole material"
        )
    return basis, out


def normalized_fractions(composition: Mapping[str, Quantity]) -> dict[str, float]:
    """The composition as fractions summing to 1.

    A certificate often lists only the major elements, so the stated
    percentages need not reach 100. Normalising makes the RATIOS -- which
    is all a Cliff-Lorimer derivation uses -- independent of whether the
    balance was quoted, while leaving the stored percentages as certified.
    """
    total = sum(q.value for q in composition.values())
    if total <= 0:
        raise StandardError("composition sums to zero")
    return {sym: q.value / total for sym, q in composition.items()}


def _bulk(name: str, raw: Any) -> Quantity | None:
    if raw is None:
        return None
    try:
        q = quantity_from(name, raw, _BULK_UNITS[name])
    except ProfileError as exc:
        raise StandardError(str(exc)) from None
    if q.unit != _BULK_UNITS[name]:
        raise StandardError(f"{name} must be in {_BULK_UNITS[name]!r}, got {q.unit!r}")
    if q.value <= 0:
        raise StandardError(f"{name} must be > 0")
    return q


def reference_region_from(raw: Any) -> ReferenceRegion:
    """One stored reference region, validated.

    `region` and `roi` are mutually exclusive for the same reason
    `resolve_region` refuses both: a caller that names two different
    scopes has a bug, and honouring one of them silently hides it.
    """
    if not isinstance(raw, Mapping):
        raise StandardError("a reference region must be an object")
    label = str(raw.get("label", "")).strip()
    if not label:
        raise StandardError("a reference region needs a label")
    region = str(raw.get("region", "") or "")
    roi = str(raw.get("roi", "") or "")
    if region and roi:
        raise StandardError(
            f"reference region {label!r} gives both 'region' and 'roi'; give one"
        )
    return ReferenceRegion(
        label=label,
        image_id=str(raw.get("image_id", "") or ""),
        region=region,
        roi=roi,
        note=str(raw.get("note", "") or ""),
    )



def standard_to_json(std: Standard) -> dict[str, Any]:
    """A standard as it is stored and transported."""
    body: dict[str, Any] = {
        **std.extra,
        "id": std.id,
        "schema": STANDARD_SCHEMA,
        "name": std.name,
        "version": std.version,
        "created_at": std.created_at,
        "updated_at": std.updated_at,
        "basis": std.basis,
        "composition": {
            sym: {
                "value": q.value,
                "unit": q.unit,
                **({"sigma": q.sigma} if q.sigma is not None else {}),
            }
            for sym, q in std.composition.items()
        },
        "text": dict(std.text),
        "regions": [
            {
                "label": r.label,
                "image_id": r.image_id,
                "region": r.region,
                "roi": r.roi,
                "note": r.note,
            }
            for r in std.regions
        ],
        "validity": {
            "valid_from": std.validity.valid_from,
            "valid_to": std.validity.valid_to,
            "beam_energy_kev": list(std.validity.beam_energy_kev)
            if std.validity.beam_energy_kev
            else None,
            "magnification": list(std.validity.magnification)
            if std.validity.magnification
            else None,
            "camera_length_mm": list(std.validity.camera_length_mm)
            if std.validity.camera_length_mm
            else None,
            "note": std.validity.note,
        },
        "provenance": {
            "source": std.provenance.source,
            "date": std.provenance.date,
            "operator": std.provenance.operator,
            "note": std.provenance.note,
        },
    }
    for name in ("density", "mass_thickness", "thickness"):
        q = getattr(std, name)
        if q is not None:
            body[name] = {
                "value": q.value,
                "unit": q.unit,
                **({"sigma": q.sigma} if q.sigma is not None else {}),
            }
    return body


def standard_from_json(raw: Mapping[str, Any]) -> Standard:
    """Read a stored standard, keeping unmodelled keys in `extra`."""
    if not isinstance(raw, Mapping):
        raise StandardError("a standard must be an object")
    for key in ("id", "name", "created_at", "updated_at"):
        if not str(raw.get(key, "")).strip():
            raise StandardError(f"a standard needs a non-empty {key!r}")
    basis, composition = composition_from(raw.get("basis"), raw.get("composition"))
    version = raw.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise StandardError("a standard's version must be an integer >= 0")
    text_raw = raw.get("text") or {}
    if not isinstance(text_raw, Mapping):
        raise StandardError("a standard's text must be an object")
    regions_raw = raw.get("regions") or []
    if not isinstance(regions_raw, (list, tuple)):
        raise StandardError("a standard's regions must be a list")
    labels = [str(r.get("label", "")) for r in regions_raw if isinstance(r, Mapping)]
    if len(set(labels)) != len(labels):
        raise StandardError("reference region labels must be unique within a standard")
    try:
        validity = validity_from(raw.get("validity"))
        provenance = provenance_from(raw.get("provenance"))
    except ProfileError as exc:
        raise StandardError(str(exc)) from None
    return Standard(
        id=str(raw["id"]),
        name=str(raw["name"]),
        version=version,
        created_at=str(raw["created_at"]),
        updated_at=str(raw["updated_at"]),
        basis=basis,
        composition=composition,
        density=_bulk("density", raw.get("density")),
        mass_thickness=_bulk("mass_thickness", raw.get("mass_thickness")),
        thickness=_bulk("thickness", raw.get("thickness")),
        text={str(k): str(v) for k, v in text_raw.items()},
        regions=tuple(reference_region_from(r) for r in regions_raw),
        validity=validity,
        provenance=provenance,
        extra={k: v for k, v in raw.items() if k not in _STANDARD_KEYS},
    )
