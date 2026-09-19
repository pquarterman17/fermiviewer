"""Which applied-profile field supplies which EDS request parameter
(ADR 0010 §3), shared by every EDS route module.

The TABLE below is EDS-only. The machinery around it -- `ParamSpec`,
`resolve_spec`, the bounds check, `resolve_beam_kv` and
`provenance_block` -- is not, and `routes/factors_eels.py` reuses it for
the one EELS parameter a profile supplies (the collection semi-angle).
Beam voltage in particular is a property of the microscope, not of which
spectrometer is looking at it.

One table, not a copy per route. The 4C review named this exact seam --
"a sibling op that never got the same fix" -- and a per-route copy of a
UNIT mapping is the worst version of it: the copies stay plausible while
disagreeing, and the symptom is a composition off by a factor nobody can
see in the response.

Kept out of `_eds_common.py` on purpose. That module is the model-based
fit machinery (peak fitting, backgrounds, the artifact pre-pass), and the
window-integration routes (`eds_quant`, `eds_maps`) need this table
WITHOUT taking on that stack.

The unit each entry names is the unit of the REQUEST FIELD, not of the
profile field -- `io.profiles_applied.profile_value` converts, or refuses
(ADR 0010 §2).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from fermiviewer.io.profiles_applied import (
    Resolved,
    UnitError,
    profile_value,
    resolve_param,
)

__all__ = [
    "EDS_PARAMS",
    "ParamSpec",
    "provenance_block",
    "resolve_beam_kv",
    "resolve_eds_param",
    "resolve_live_time_s",
    "resolve_spec",
]


@dataclass(frozen=True)
class ParamSpec:
    """A request field a profile can supply."""

    #: unit of the REQUEST field; the profile value is converted into it
    unit: str
    #: ``(kind, field)`` in precedence order
    candidates: tuple[tuple[str, str], ...]
    #: the route's own literal, used when nothing else supplies one
    default: float
    #: exclusive bounds the RESOLVED value must satisfy, mirroring the
    #: `Field(gt=..., lt=...)` on the request field. A profile value never
    #: passes through pydantic, so without this a stored 120 deg takeoff
    #: angle would reach the calculation while a TYPED 120 is rejected --
    #: the guard would protect only the input path nobody gets wrong.
    gt: float | None = None
    lt: float | None = None


#: Request field name -> where it comes from. Only fields that a route
#: actually consumes today appear here; a profile field with no consumer
#: (`detector.solid_angle`, `detector.efficiency`,
#: `detector.window_thickness`, `acquisition.dwell_time`) is deliberately
#: absent rather than listed against a route that would ignore it, as is a
#: request field no profile states (`density_g_cm3`, `thickness_nm` -- both
#: are properties of the SPECIMEN, which no instrument profile describes).
EDS_PARAMS: dict[str, ParamSpec] = {
    "take_off_angle_deg": ParamSpec(
        unit="deg",
        candidates=(("detector", "takeoff_angle"),),
        default=20.0,
        # `zaf_correction` and `zeta_quantify` both refuse outside this
        gt=0.0,
        lt=90.0,
    ),
    "probe_current_na": ParamSpec(
        # `dose_electrons` refuses a non-positive current
        # the store keeps picoamps and `dose_electrons` takes nanoamps --
        # the 1000x this whole module exists to convert rather than assume
        unit="nA",
        candidates=(("acquisition", "probe_current"),),
        default=1.0,
        gt=0.0,
    ),
    "live_time_s": ParamSpec(
        unit="s",
        candidates=(("acquisition", "live_time"),),
        default=100.0,
        gt=0.0,  # `dose_electrons` refuses a non-positive live time
    ),
}


def resolve_eds_param(
    metadata: Mapping[str, Any], name: str, requested: float | None
) -> Resolved:
    """One `EDS_PARAMS` entry resolved for this image, request value first."""
    return resolve_spec(metadata, name, EDS_PARAMS[name], requested)


def resolve_spec(
    metadata: Mapping[str, Any],
    name: str,
    spec: ParamSpec,
    requested: float | None,
) -> Resolved:
    """Any `ParamSpec` resolved for this image, request value first.

    An unconvertible stored unit is a 422, never a silent fall through to
    the built-in default: answering with 20 deg because the applied
    profile said something this build could not read would hide the one
    thing the user needs to know.
    """
    try:
        resolved = resolve_param(
            metadata,
            requested=requested,
            candidates=spec.candidates,
            unit=spec.unit,
            default=spec.default,
        )
    except UnitError as exc:
        raise HTTPException(422, f"{name}: {exc}") from None
    return _in_bounds(name, spec, resolved)


def _in_bounds(name: str, spec: ParamSpec, resolved: Resolved) -> Resolved:
    """Enforce `spec`'s bounds on an already-resolved value.

    A request value has been through pydantic; a PROFILE value has not,
    and neither has a default. Checking here covers all three by the one
    rule, and names the origin in the message so a user who typed nothing
    is not told to fix their input.
    """
    where = resolved.field if resolved.origin == "profile" else resolved.origin
    if spec.gt is not None and not resolved.value > spec.gt:
        raise HTTPException(
            422, f"{name}: {resolved.value:g} {resolved.unit} (from {where}) must be > {spec.gt:g}"
        )
    if spec.lt is not None and not resolved.value < spec.lt:
        raise HTTPException(
            422, f"{name}: {resolved.value:g} {resolved.unit} (from {where}) must be < {spec.lt:g}"
        )
    return resolved


def resolve_beam_kv(metadata: Mapping[str, Any], requested: float | None) -> Resolved:
    """Beam voltage in kV, from a microscope or an acquisition profile.

    Two sources, and they are not the same quantity. `microscope.
    accelerating_voltage` IS a voltage (kV) and converts directly.
    `acquisition.beam_energy` is an ENERGY (keV); for a singly-charged
    electron accelerated through V kilovolts the kinetic energy is
    numerically V keV, so the magnitude carries across untouched. That
    equivalence is named here, at the one place that relies on it, rather
    than by putting volts and electronvolts in one dimension in
    `io.profile_units` -- there it would silently license every other
    voltage/energy conversion in the codebase.

    The acquisition profile wins: it describes THIS session, while the
    microscope profile describes an instrument that runs at several
    voltages.
    """
    if requested is not None:
        return Resolved(value=float(requested), unit="kV", origin="request")
    try:
        energy = profile_value(metadata, "acquisition", "beam_energy", unit="keV")
        if energy is not None:
            return Resolved(
                value=energy.value,  # keV -> kV: the electron equivalence above
                unit="kV",
                origin="profile",
                source=energy.source,
                field=energy.field,
                sigma=energy.sigma,
            )
        volts = profile_value(metadata, "microscope", "accelerating_voltage", unit="kV")
    except UnitError as exc:
        raise HTTPException(422, f"beam_kv: {exc}") from None
    if volts is not None:
        return Resolved(
            value=volts.value,
            unit="kV",
            origin="profile",
            source=volts.source,
            field=volts.field,
            sigma=volts.sigma,
        )
    return Resolved(value=200.0, unit="kV", origin="default")


def resolve_live_time_s(
    metadata: Mapping[str, Any], requested: float | None
) -> Resolved:
    """Live time in seconds, derived from real time and dead time when the
    profile states those instead.

    A detector reports real (wall-clock) time and a dead-time percentage;
    live time is what the dose integral needs. An acquisition profile may
    carry either form, so a profile that states `real_time` and
    `dead_time` but no `live_time` is not "missing" the parameter --
    ``live = real x (1 - dead/100)``.
    """
    if requested is not None:
        return Resolved(value=float(requested), unit="s", origin="request")
    direct = resolve_eds_param(metadata, "live_time_s", None)
    if direct.origin == "profile":
        return direct
    try:
        real = profile_value(metadata, "acquisition", "real_time", unit="s")
        dead = profile_value(metadata, "acquisition", "dead_time", unit="fraction")
    except UnitError as exc:
        raise HTTPException(422, f"live_time_s: {exc}") from None
    if real is None or dead is None:
        return direct  # the default
    if not 0.0 <= dead.value < 1.0:
        raise HTTPException(
            422, f"live_time_s: dead time {dead.value * 100:g}% is outside [0, 100)"
        )
    return _in_bounds(
        "live_time_s",
        EDS_PARAMS["live_time_s"],
        Resolved(
            value=real.value * (1.0 - dead.value),
            unit="s",
            origin="profile",
            source=real.source,
            field="acquisition.real_time x (1 - acquisition.dead_time)",
        ),
    )


def provenance_block(resolved: Mapping[str, Resolved]) -> dict[str, Any]:
    """The `calibration` block a response carries: per parameter, the value
    used, its unit, and whether it came from the request, an applied
    profile (which one, which field) or the route default.

    Reported for EVERY resolved parameter including the defaults, so the
    absence of a profile is as visible as its presence -- a composition
    computed with a 20 deg placeholder takeoff angle should not look the
    same as one computed with a measured 35 deg.
    """
    return {name: r.as_dict() for name, r in resolved.items()}
