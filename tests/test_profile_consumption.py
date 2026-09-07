"""Profiles feeding EDS quantification (ADR 0010, roadmap 5a box 3).

The claim under test is narrow and the whole point of the box: a value
the user typed always wins; otherwise the image's applied profiles supply
it, CONVERTED into the unit the consumer's signature names; failing both,
the route's own literal. Every path says which of the three it took.

The conversions are where a profile silently corrupts a published number,
so they are pinned as arithmetic rather than as "a profile was used":
picoamps into a nanoamp signature is a factor of 1000, and a factor of
1000 on the dose is a factor of 1000 on the mass-thickness.
"""

from __future__ import annotations

import math

import pytest

from fermiviewer.io.profile_units import UnitError, convert, same_dimension
from fermiviewer.io.profiles_applied import (
    attach_profile,
    profile_value,
    resolve_param,
)
from fermiviewer.io.profiles_model import Profile, Provenance, Quantity, Validity


def _profile(kind: str, fields: dict[str, Quantity], *, pid: str = "p1", version: int = 3) -> dict:
    """A snapshot as `attach_profile` stores it."""
    prof = Profile(
        id=pid,
        name=f"{kind} under test",
        kind=kind,
        version=version,
        created_at="2026-09-07T00:00:00Z",
        updated_at="2026-09-07T00:00:00Z",
        fields=fields,
        text={},
        validity=Validity(),
        provenance=Provenance(source="manual"),
    )
    from fermiviewer.io.profiles_applied import snapshot_profile

    return snapshot_profile(prof, applied_at="2026-09-07T00:00:00Z")


def _meta(*snapshots: dict) -> dict:
    meta: dict = {}
    for snap in snapshots:
        meta = attach_profile(meta, snap)
    return meta


# ── the unit table ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "src", "dst", "want"),
    [
        (500.0, "pA", "nA", 0.5),        # the store's unit into dose_electrons'
        (1.0, "nA", "pA", 1000.0),
        (1000.0, "us", "s", 1e-3),
        (2.0, "um", "nm", 2000.0),       # exact, not 1999.9999999999998
        (30.0, "%", "fraction", 0.3),
        (180.0, "deg", "rad", math.pi),
        (20.0, "keV", "eV", 20000.0),
    ],
)
def test_convert_is_exact(value: float, src: str, dst: str, want: float) -> None:
    assert convert(value, src, dst) == pytest.approx(want, rel=0, abs=1e-12)


def test_convert_refuses_across_dimensions() -> None:
    """No best-effort passthrough. A number of unknown scale reaching a
    composition is the failure this table exists to prevent, so an
    impossible conversion raises rather than returning the input."""
    with pytest.raises(UnitError, match="cannot convert"):
        convert(1.0, "s", "nA")
    with pytest.raises(UnitError, match="unknown unit"):
        convert(1.0, "furlong", "nm")


def test_volts_and_electronvolts_are_not_interchangeable() -> None:
    """kV -> keV is refused by the table on purpose. The equivalence holds
    for a singly-charged electron and is named at the one call site that
    relies on it (`resolve_beam_kv`), not licensed for every conversion."""
    assert not same_dimension("kV", "keV")
    with pytest.raises(UnitError):
        convert(200.0, "kV", "keV")


# ── the resolver ──────────────────────────────────────────────────────


def test_profile_value_converts_into_the_consumers_unit() -> None:
    meta = _meta(_profile("acquisition", {"probe_current": Quantity(500.0, "pA")}))
    got = profile_value(meta, "acquisition", "probe_current", unit="nA")
    assert got is not None
    assert got.value == 0.5
    assert got.unit == "nA"
    assert got.field == "acquisition.probe_current"
    assert got.source == "profile:p1@3"


def test_profile_value_carries_sigma_in_the_same_unit() -> None:
    meta = _meta(
        _profile("acquisition", {"probe_current": Quantity(500.0, "pA", sigma=50.0)})
    )
    got = profile_value(meta, "acquisition", "probe_current", unit="nA")
    assert got is not None and got.sigma == pytest.approx(0.05)


def test_profile_value_raises_on_an_unconvertible_unit() -> None:
    """A hand-edited store stating a takeoff angle in seconds must stop the
    request, not contribute an unknown magnitude."""
    meta = _meta(_profile("detector", {"takeoff_angle": Quantity(35.0, "s")}))
    with pytest.raises(UnitError):
        profile_value(meta, "detector", "takeoff_angle", unit="deg")


def test_a_bare_number_takes_the_fields_canonical_unit() -> None:
    """`validate_fields` writes an explicit unit, so a bare number only
    reaches here from a hand-edited or foreign store. Resolving it to a
    UNITLESS number would then convert as if it were already degrees --
    right by luck here, wrong for probe current."""
    snap = _profile("acquisition", {"probe_current": Quantity(1.0, "pA")})
    snap["fields"]["probe_current"] = 2000.0  # as a hand edit leaves it
    got = profile_value(_meta(snap), "acquisition", "probe_current", unit="nA")
    assert got is not None and got.value == pytest.approx(2.0)


def test_request_value_beats_the_profile() -> None:
    """The rule the box is written around."""
    meta = _meta(_profile("detector", {"takeoff_angle": Quantity(35.0, "deg")}))
    r = resolve_param(
        meta, requested=12.0, candidates=(("detector", "takeoff_angle"),), unit="deg", default=20.0
    )
    assert (r.value, r.origin) == (12.0, "request")


def test_profile_beats_the_default() -> None:
    meta = _meta(_profile("detector", {"takeoff_angle": Quantity(35.0, "deg")}))
    r = resolve_param(
        meta, requested=None, candidates=(("detector", "takeoff_angle"),), unit="deg", default=20.0
    )
    assert (r.value, r.origin, r.field) == (35.0, "profile", "detector.takeoff_angle")


def test_default_when_nothing_supplies_one() -> None:
    r = resolve_param(
        {}, requested=None, candidates=(("detector", "takeoff_angle"),), unit="deg", default=20.0
    )
    assert (r.value, r.origin, r.source) == (20.0, "default", None)


def test_candidates_are_tried_in_order() -> None:
    meta = _meta(
        _profile("microscope", {"accelerating_voltage": Quantity(80.0, "kV")}, pid="scope"),
    )
    r = resolve_param(
        meta,
        requested=None,
        candidates=(("acquisition", "beam_energy"), ("microscope", "accelerating_voltage")),
        unit="kV",
        default=200.0,
    )
    assert (r.value, r.field) == (80.0, "microscope.accelerating_voltage")


def test_resolved_reports_its_provenance() -> None:
    meta = _meta(_profile("detector", {"takeoff_angle": Quantity(35.0, "deg", sigma=1.5)}))
    r = resolve_param(
        meta, requested=None, candidates=(("detector", "takeoff_angle"),), unit="deg", default=20.0
    )
    assert r.as_dict() == {
        "value": 35.0,
        "unit": "deg",
        "origin": "profile",
        "source": "profile:p1@3",
        "field": "detector.takeoff_angle",
        "sigma": 1.5,
    }
