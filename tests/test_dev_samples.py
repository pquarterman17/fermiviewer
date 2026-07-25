"""Dev-only sample auto-load: resolver + endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fermiviewer.devsamples import DEFAULT_EXTS, corpus_root, find_sample_files
from fermiviewer.server import create_app

pytestmark = pytest.mark.api


def test_corpus_root_is_the_only_resolver(ml_datasets: Path) -> None:
    """conftest's corpus fixture and devsamples must agree on the root.

    They resolved the path independently until the checkouts moved off
    OneDrive; devsamples then pointed at a directory that no longer
    existed while the fixture found the corpus, so this test's sibling
    failed while the rest of the realdata suite skipped silently. Pin
    the agreement so a future move breaks one obvious assertion.
    """
    assert ml_datasets == corpus_root() / "+test_datasets"
    assert ml_datasets.is_dir()


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
