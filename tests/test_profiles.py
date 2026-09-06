"""Calibration profiles, pure layer (ADR 0009, roadmap 5a boxes 1, 4, 5).

The record types and their validation, the JSON round trip and its
unknown-key carry, the versioned per-user store with history, the legacy
calibration-DB import, and the applicability check against what an
image's metadata states in each parser's spelling.
"""

from __future__ import annotations

import json
import threading
import warnings
from pathlib import Path

import pytest

from fermiviewer.io import profiles_db
from fermiviewer.io.calibration_db import list_calibrations, save_calibration
from fermiviewer.io.profiles_applied import (
    applied_profiles,
    attach_profile,
    detach_profile,
    profile_quantity,
    snapshot_profile,
)
from fermiviewer.io.profiles_db import (
    applicability,
    create_profile,
    delete_profile,
    get_profile,
    image_conditions,
    import_legacy_calibrations,
    list_profiles,
    profile_history,
    update_profile,
)
from fermiviewer.io.profiles_model import (
    FIELD_UNITS,
    PROFILE_KINDS,
    PROFILE_SCHEMA,
    Profile,
    ProfileError,
    Provenance,
    Quantity,
    Validity,
    profile_from_json,
    profile_to_json,
    spatial_spacing,
    validate_fields,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FV_PROFILES_PATH", str(tmp_path / "profiles.json"))
    monkeypatch.setenv("FV_CALIB_PATH", str(tmp_path / "calib.json"))


def _clock(stamps: list[str]):
    it = iter(stamps)
    return lambda: next(it)


DETECTOR_FIELDS = {
    "solid_angle": {"value": 0.7, "unit": "sr", "sigma": 0.05},
    "takeoff_angle": {"value": 22.0, "unit": "deg"},
    "energy_resolution": 129.0,  # bare number: takes the canonical unit
}


# ── model ─────────────────────────────────────────────────────────────


def test_fields_become_quantities_and_a_bare_number_takes_the_canonical_unit() -> None:
    fields = validate_fields("detector", DETECTOR_FIELDS)
    assert fields["solid_angle"] == Quantity(0.7, "sr", 0.05)
    assert fields["takeoff_angle"] == Quantity(22.0, "deg", None)  # sigma absent, not 0
    assert fields["energy_resolution"] == Quantity(129.0, "eV", None)
    assert validate_fields("acquisition", {"beam_energy": 200})["beam_energy"].unit == "keV"
    assert (
        validate_fields("acquisition", {"beam_energy": {"value": 200}})["beam_energy"].unit == "keV"
    )


def test_a_known_field_stated_in_another_unit_is_refused() -> None:
    """beam_energy in eV where every consumer reads keV is the silent error
    profiles exist to remove."""
    with pytest.raises(ProfileError, match="'keV'"):
        validate_fields("acquisition", {"beam_energy": {"value": 200000, "unit": "eV"}})
    with pytest.raises(ProfileError, match="'deg'"):
        validate_fields("detector", {"takeoff_angle": {"value": 0.38, "unit": "rad"}})


def test_an_unknown_field_is_accepted_as_given() -> None:
    fields = validate_fields("camera", {"lab_gain_factor": {"value": 1.7, "unit": "au"}})
    assert fields["lab_gain_factor"].unit == "au"
    assert validate_fields("camera", {"lab_gain_factor": 1.7})["lab_gain_factor"].unit == ""
    # a known DIMENSIONLESS field takes any unit string
    assert validate_fields("camera", {"binning": {"value": 2, "unit": "x"}})["binning"].unit == "x"


@pytest.mark.parametrize(
    "bad",
    [
        {"x": {"value": float("nan"), "unit": ""}},
        {"x": {"value": 1.0, "unit": "", "sigma": -1}},
        {"x": {"unit": "sr"}},
        {"x": "seven"},
        {"": 1.0},
    ],
)
def test_malformed_fields_are_refused(bad: dict) -> None:
    with pytest.raises(ProfileError):
        validate_fields("detector", bad)


def test_unknown_kind_is_refused_and_every_kind_has_a_field_table() -> None:
    with pytest.raises(ProfileError, match="kind"):
        validate_fields("stage", {})
    assert set(FIELD_UNITS) == PROFILE_KINDS


def test_validity_and_provenance_are_validated() -> None:
    p = profile_from_json(
        {
            "id": "p1",
            "name": "Ultim",
            "kind": "detector",
            "validity": {"valid_from": "2026-01-01", "beam_energy_kev": [80, 300]},
            "provenance": {"source": "datasheet", "date": "2025-12-31T10:00", "operator": "pq"},
        }
    )
    assert p.validity == Validity(valid_from="2026-01-01", beam_energy_kev=(80.0, 300.0))
    assert p.provenance == Provenance(source="datasheet", date="2025-12-31", operator="pq")
    with pytest.raises(ProfileError, match="low bound"):
        profile_from_json(
            {"id": "p", "name": "n", "kind": "detector", "validity": {"magnification": [10, 1]}}
        )
    with pytest.raises(ProfileError, match="after valid_to"):
        profile_from_json(
            {
                "id": "p",
                "name": "n",
                "kind": "detector",
                "validity": {"valid_from": "2026-02-01", "valid_to": "2026-01-01"},
            }
        )
    with pytest.raises(ProfileError, match="ISO date"):
        profile_from_json(
            {"id": "p", "name": "n", "kind": "detector", "provenance": {"date": "yesterday"}}
        )


def test_json_round_trip_is_identity_and_carries_unknown_keys() -> None:
    raw = {
        "id": "p1",
        "name": "Ultim Max",
        "kind": "detector",
        "version": 3,
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-06T00:00:00+00:00",
        "fields": {"solid_angle": {"value": 0.7, "unit": "sr", "sigma": 0.05}},
        "text": {"model": "Ultim Max 170", "window": "polymer"},
        "validity": {"beam_energy_kev": [80, 300]},
        "provenance": {"source": "datasheet"},
        "lab_only": {"rack": 3},  # a key this build does not model
    }
    p = profile_from_json(raw)
    assert p.extra == {"lab_only": {"rack": 3}}
    out = profile_to_json(p)
    assert out["lab_only"] == {"rack": 3}
    assert out["schema"] == PROFILE_SCHEMA
    assert profile_from_json(out) == p
    # a snapshot reads back as the same profile: its additions ride `extra`
    snap = snapshot_profile(p, applied_at="2026-09-06T01:02:03+00:00", applicability=("x",))
    back = profile_from_json(snap)
    assert (back.id, back.version, back.fields) == (p.id, p.version, p.fields)
    assert back.extra["applied_at"] == "2026-09-06T01:02:03+00:00"
    assert back.extra["applicability"] == ["x"]


def test_a_later_schema_is_refused_not_downgraded() -> None:
    with pytest.raises(ProfileError, match="schema 2"):
        profile_from_json({"id": "p", "name": "n", "kind": "camera", "schema": 2})


def test_spatial_spacing_needs_both_extents_in_one_unit() -> None:
    def acq(**fields):
        return Profile(
            id="a", name="a", kind="acquisition", fields=validate_fields("acquisition", fields)
        )

    assert spatial_spacing(acq()) is None
    assert spatial_spacing(acq(beam_energy={"value": 200, "unit": "keV"})) is None
    both = acq(
        pixel_size_row={"value": 0.5, "unit": "nm"}, pixel_size_column={"value": 2.0, "unit": "nm"}
    )
    assert spatial_spacing(both) == ((0.5, 2.0), "nm")
    with pytest.raises(ProfileError, match="share a unit"):
        spatial_spacing(
            acq(
                pixel_size_row={"value": 0.5, "unit": "nm"},
                pixel_size_column={"value": 2.0, "unit": "um"},
            )
        )
    with pytest.raises(ProfileError, match="together"):
        spatial_spacing(acq(pixel_size_row={"value": 0.5, "unit": "nm"}))
    with pytest.raises(ProfileError, match="together"):
        create_profile(
            name="half",
            kind="acquisition",
            fields={"pixel_size_column": {"value": 0.5, "unit": "nm"}},
        )
    # a detector never states a spacing, whatever fields it carries
    det = Profile(
        id="d",
        name="d",
        kind="detector",
        fields={"pixel_size_row": Quantity(1, "nm"), "pixel_size_column": Quantity(1, "nm")},
    )
    assert spatial_spacing(det) is None


def test_attach_detach_and_resolve_on_image_metadata() -> None:
    det = profile_from_json(
        {
            "id": "d1",
            "name": "det",
            "kind": "detector",
            "fields": {"takeoff_angle": {"value": 22, "unit": "deg"}},
        }
    )
    mic = profile_from_json({"id": "m1", "name": "mic", "kind": "microscope"})
    meta = {"beam_kv": 200}
    meta = attach_profile(meta, snapshot_profile(det, applied_at="t"))
    meta = attach_profile(meta, snapshot_profile(mic, applied_at="t"))
    assert set(applied_profiles(meta)) == {"detector", "microscope"}
    assert profile_quantity(meta, "detector", "takeoff_angle") == Quantity(22.0, "deg")
    assert profile_quantity(meta, "detector", "solid_angle") is None
    assert profile_quantity(meta, "camera", "gain") is None
    # a second detector REPLACES the first: one profile per kind
    det2 = profile_from_json({"id": "d2", "name": "det2", "kind": "detector"})
    meta = attach_profile(meta, snapshot_profile(det2, applied_at="t"))
    assert applied_profiles(meta)["detector"]["id"] == "d2"
    meta = detach_profile(meta, "detector")
    meta = detach_profile(meta, "microscope")
    assert "profiles" not in meta  # the key goes away with the last profile
    assert meta == {"beam_kv": 200}
    # a foreign value under the key is read as none, never raised on
    assert applied_profiles({"profiles": "junk"}) == {}
    assert applied_profiles({"profiles": {"detector": 3}}) == {}


# ── store ─────────────────────────────────────────────────────────────


def test_create_update_history_delete() -> None:
    clock = _clock(["t1", "t2", "t3"])
    p1 = create_profile(
        name="Ultim",
        kind="detector",
        fields=DETECTOR_FIELDS,
        provenance={"source": "datasheet"},
        clock=clock,
    )
    assert (p1.version, p1.created_at, p1.updated_at) == (1, "t1", "t1")
    assert get_profile(p1.id) == p1

    p2 = update_profile(p1.id, fields={"solid_angle": {"value": 0.9, "unit": "sr"}}, clock=clock)
    assert (p2.version, p2.created_at, p2.updated_at) == (2, "t1", "t2")
    assert p2.fields == {"solid_angle": Quantity(0.9, "sr")}  # replaced wholesale
    assert p2.provenance.source == "datasheet"  # omitted parts kept
    assert p2.name == "Ultim"

    p3 = update_profile(p1.id, name="Ultim Max", clock=clock)
    assert (p3.version, p3.fields) == (3, p2.fields)

    versions = profile_history(p1.id)
    assert [v.version for v in versions] == [1, 2, 3]
    assert versions[0] == p1  # the first version is exactly what was created
    assert get_profile(p1.id) == p3
    assert [p.id for p in list_profiles()] == [p1.id]
    assert list_profiles("camera") == []

    assert delete_profile(p1.id) is True
    assert delete_profile(p1.id) is False
    assert get_profile(p1.id) is None
    with pytest.raises(KeyError):
        profile_history(p1.id)
    with pytest.raises(KeyError):
        update_profile(p1.id, name="x")


def test_kind_is_immutable_and_names_must_be_non_empty() -> None:
    p = create_profile(name="cam", kind="camera")
    with pytest.raises(ProfileError):
        create_profile(name="   ", kind="camera")
    with pytest.raises(ProfileError, match="kind"):
        create_profile(name="x", kind="stage")
    # the store never offers a kind change; the record type says so too
    assert get_profile(p.id).kind == "camera"


def test_list_orders_by_name_and_skips_a_malformed_entry(tmp_path: Path) -> None:
    b = create_profile(name="beta", kind="camera")
    a = create_profile(name="Alpha", kind="camera")
    path = tmp_path / "profiles.json"
    data = json.loads(path.read_text())
    data["profiles"]["bad"] = {"name": "broken", "kind": "camera", "fields": {"x": "seven"}}
    path.write_text(json.dumps(data))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        listed = list_profiles()
    assert [p.id for p in listed] == [a.id, b.id]
    assert any("skipped" in str(w.message) for w in caught)


def test_a_corrupt_store_is_backed_up_and_a_later_schema_refused(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text("{not json")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert list_profiles() == []
    assert any("corrupt" in str(w.message) for w in caught)
    assert list(tmp_path.glob("profiles.json.corrupt-*"))
    path.write_text(json.dumps({"schema": 99, "profiles": {}}))
    with pytest.raises(ProfileError, match="schema 99"):
        list_profiles()


def test_concurrent_creates_do_not_clobber_each_other(tmp_path: Path) -> None:
    """Eight threads each create one profile after a barrier, so their
    _load()/_save() transactions would race without `_LOCK` -- the last
    writer's `_save` would silently drop everyone else's profile."""
    n = 8
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            barrier.wait()
            create_profile(name=f"p{i}", kind="camera")
        except BaseException as exc:  # noqa: BLE001 -- surfaced via `errors`
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert {p.name for p in list_profiles()} == {f"p{i}" for i in range(n)}
    path = tmp_path / "profiles.json"
    data = json.loads(path.read_text())
    assert len(data["profiles"]) == n
    assert not list(tmp_path.glob("profiles.json.tmp-*"))


def test_store_file_shape_and_atomic_write(tmp_path: Path) -> None:
    p = create_profile(name="x", kind="microscope")
    data = json.loads((tmp_path / "profiles.json").read_text())
    assert data["schema"] == PROFILE_SCHEMA
    assert data["profiles"][p.id]["history"] == []
    assert data["profiles"][p.id]["version"] == 1
    assert not list(tmp_path.glob("profiles.json.tmp-*"))
    assert profiles_db.db_path() == tmp_path / "profiles.json"


# ── legacy import (migration) ─────────────────────────────────────────


def test_legacy_calibrations_import_square_per_axis_malformed_idempotent() -> None:
    save_calibration("Titan|50000", 0.42, "nm", note="Au grating")
    save_calibration("AFM|1", None, "nm", pixel_spacing=(0.5, 2.0))
    entries = {
        **list_calibrations(),
        "Broken|?": {"pixel_size": -1, "unit": "nm", "note": "", "saved": "2026-09-01 10:00"},
    }
    created, skipped = import_legacy_calibrations(entries, clock=_clock(["t1", "t2"]))
    by_name = {p.name: p for p in created}
    assert set(by_name) == {"Titan|50000", "AFM|1"}
    assert skipped == ["'Broken|?': malformed entry"]

    titan = by_name["Titan|50000"]
    assert titan.kind == "acquisition"
    assert spatial_spacing(titan) == ((0.42, 0.42), "nm")  # a legacy entry is square
    assert titan.fields["magnification"] == Quantity(50000.0, "")
    assert titan.text == {"legacy_key": "Titan|50000", "instrument": "Titan"}
    assert titan.provenance.source == "legacy calibration DB"
    assert titan.provenance.note == "Au grating"
    assert titan.provenance.date is not None and len(titan.provenance.date) == 10

    afm = by_name["AFM|1"]
    assert spatial_spacing(afm) == ((0.5, 2.0), "nm")  # a per-axis entry stays per axis
    assert afm.fields["magnification"] == Quantity(1.0, "")

    # idempotent: nothing new, and the existing profiles are untouched
    again, skipped_again = import_legacy_calibrations(entries)
    assert again == []
    assert sorted(skipped_again)[:2] == [
        "'AFM|1': already imported",
        "'Broken|?': malformed entry",
    ]
    assert get_profile(titan.id) == titan
    assert len(list_profiles("acquisition")) == 2


# ── applicability ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "metadata, expected",
    [
        ({"beam_kv": 200}, 200.0),  # FEI / Zeiss / JEOL / EDAX
        ({"voltage_kV": 30}, 30.0),  # Bruker
        ({"acceleration_voltage_v": 80000}, 80.0),  # TIA .emi, in volts
        ({"image_tags": {"Microscope Info": {"Voltage": 300000}}}, 300.0),  # DM, in volts
        ({"beam_kv": "200"}, 200.0),
        ({}, None),
    ],
)
def test_image_conditions_reads_every_voltage_spelling(metadata: dict, expected) -> None:
    assert image_conditions(metadata).get("beam_energy_kev") == expected


def test_image_conditions_reads_magnification_in_both_spellings() -> None:
    assert image_conditions({"magnification": 50000})["magnification"] == 50000.0
    nested = {"image_tags": {"Indicated Magnification": 25000.0}}
    assert image_conditions(nested)["magnification"] == 25000.0
    assert "magnification" not in image_conditions({"magnification": "unknown"})


def test_applicability_names_each_violation_and_skips_unstated_conditions() -> None:
    p = profile_from_json(
        {
            "id": "p",
            "name": "n",
            "kind": "detector",
            "validity": {
                "valid_from": "2026-01-01",
                "valid_to": "2026-06-30",
                "beam_energy_kev": [80, 300],
                "magnification": [1000, 100000],
                "camera_length_mm": [100, 500],
            },
        }
    )
    assert applicability(p, {"beam_kv": 200, "magnification": 50000}) == ()
    reasons = applicability(p, {"beam_kv": 30, "magnification": 500000}, on="2026-09-06")
    assert reasons == (
        "beam_energy 30 keV is outside the profile's 80-300 keV range",
        "magnification 500000 x is outside the profile's 1000-100000 x range",
        "used on 2026-09-06, after the profile expired (2026-06-30)",
    )
    assert applicability(p, {}, on="2025-12-31") == (
        "used on 2025-12-31, before the profile is valid (2026-01-01)",
    )
    # nothing stated, no window checked → nothing to report, which is not "in range"
    assert applicability(p, {}) == ()
    assert applicability(p, {"camera_length_mm": 800}) == (
        "camera_length 800 mm is outside the profile's 100-500 mm range",
    )
