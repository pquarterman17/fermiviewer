"""`_date` (via `profile_from_json`): a real calendar date, not just dashes
in the right places (review finding on `profiles_model._date`)."""

from __future__ import annotations

import pytest

from fermiviewer.io.profiles_model import ProfileError, profile_from_json


def _profile(*, valid_from=None, valid_to=None, date=None):
    body = {"id": "p", "name": "n", "kind": "detector"}
    if valid_from is not None or valid_to is not None:
        body["validity"] = {"valid_from": valid_from, "valid_to": valid_to}
    if date is not None:
        body["provenance"] = {"date": date}
    return body


def test_plain_date_is_accepted() -> None:
    p = profile_from_json(_profile(date="2026-09-01"))
    assert p.provenance.date == "2026-09-01"


def test_t_separated_timestamp_is_truncated_to_the_date() -> None:
    p = profile_from_json(_profile(date="2025-12-31T10:00"))
    assert p.provenance.date == "2025-12-31"


def test_space_separated_timestamp_is_truncated_to_the_date() -> None:
    p = profile_from_json(_profile(date="2026-09-01 10:00"))
    assert p.provenance.date == "2026-09-01"


def test_leap_day_is_accepted() -> None:
    p = profile_from_json(_profile(date="2024-02-29"))
    assert p.provenance.date == "2024-02-29"


def test_non_leap_year_february_29_is_refused() -> None:
    with pytest.raises(ProfileError, match="ISO date"):
        profile_from_json(_profile(date="2023-02-29"))


def test_invalid_month_is_refused() -> None:
    with pytest.raises(ProfileError, match="ISO date"):
        profile_from_json(_profile(date="2026-99-99"))


def test_invalid_day_is_refused() -> None:
    with pytest.raises(ProfileError, match="ISO date"):
        profile_from_json(_profile(date="2026-02-31"))


def test_non_numeric_date_is_refused() -> None:
    with pytest.raises(ProfileError, match="ISO date"):
        profile_from_json(_profile(date="2026-ab-cd"))


def test_suffix_without_a_separator_is_refused() -> None:
    with pytest.raises(ProfileError, match="ISO date"):
        profile_from_json(_profile(date="2026-01-01x"))


def test_non_string_date_is_refused() -> None:
    with pytest.raises(ProfileError, match="ISO date"):
        profile_from_json(_profile(date=20260901))


def test_valid_from_after_valid_to_is_still_refused() -> None:
    with pytest.raises(ProfileError, match="after valid_to"):
        profile_from_json(_profile(valid_from="2026-02-01", valid_to="2026-01-01"))
