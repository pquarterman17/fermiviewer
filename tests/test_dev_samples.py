"""Dev-only sample auto-load: resolver + endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fermiviewer.devsamples import DEFAULT_EXTS, find_sample_files
from fermiviewer.server import create_app

pytestmark = pytest.mark.api


def test_sample_files_endpoint_returns_list() -> None:
    """Always 200 + a list, even when the corpus is absent (returns [])."""
    client = TestClient(create_app())
    r = client.get("/api/dev/sample-files")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert all(isinstance(p, str) for p in body)


def test_find_sample_files_match_extensions(ml_datasets: Path) -> None:
    """With the corpus present (fixture skips otherwise), every resolved
    path exists and carries one of the requested extensions."""
    paths = find_sample_files()
    assert paths, "expected at least one sample when corpus present"
    assert len(paths) == len(set(paths)), "no duplicate paths"
    for p in paths:
        assert p.is_file()
        assert p.suffix.lower() in DEFAULT_EXTS
