"""Provenance log (Scripting #5): step recording, ancestry reconstruction,
JSON + methods-Markdown export, and capture through the api.Session."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import fermiviewer.api as fv
from fermiviewer import __version__
from fermiviewer.ops.provenance import ProvenanceLog, ProvenanceStep
from fixtures.miniemd import write_ncem_emd

pytestmark = pytest.mark.parser


# ── pure ProvenanceLog ───────────────────────────────────────────────


def test_ancestry_reconstructs_a_three_step_chain() -> None:
    log = ProvenanceLog()
    log.record(ProvenanceStep("gaussian", {"sigma": 2.0}, "gaussian", ("a",), "b",
                              input_names=("scan.dm4",), timestamp="t1"))
    log.record(ProvenanceStep("median", {"window_size": 3}, "median", ("b",), "c",
                              timestamp="t2"))
    log.record(ProvenanceStep("rotate90", {}, "rotate90", ("c",), "d", timestamp="t3"))
    chain = log.ancestry("d")
    assert [s.op for s in chain] == ["gaussian", "median", "rotate90"]  # root→leaf
    # unrelated id → empty
    assert log.ancestry("zzz") == []


def test_to_markdown_renders_methods_paragraph() -> None:
    log = ProvenanceLog()
    log.record(ProvenanceStep("gaussian", {"sigma": 2.0}, "gaussian", ("a",), "b",
                              input_names=("scan.dm4",), version="9.9.9", timestamp="t"))
    log.record(ProvenanceStep("median", {"window_size": 3}, "median", ("b",), "c",
                              version="9.9.9", timestamp="t"))
    md = log.to_markdown("c")
    assert "scan.dm4" in md
    assert "fermiviewer 9.9.9" in md
    assert "gaussian (sigma=2.0)" in md
    assert "median (window_size=3)" in md


def test_cycle_guard_does_not_hang() -> None:
    log = ProvenanceLog()
    log.record(ProvenanceStep("op", {}, "op", ("y",), "x", timestamp="t"))
    log.record(ProvenanceStep("op", {}, "op", ("x",), "y", timestamp="t"))
    # mutually-referential lineage must terminate
    assert len(log.ancestry("x")) <= 2


# ── capture through the public façade ────────────────────────────────


@pytest.fixture()
def image_path(tmp_path) -> Path:
    img = np.arange(48, dtype=np.float32).reshape(6, 8)
    return write_ncem_emd(
        tmp_path / "scan.emd",
        img,
        [(np.arange(6) * 1.0, "y", "nm"), (np.arange(8) * 1.0, "x", "nm")],
    )


def test_session_records_each_op(image_path) -> None:
    sess = fv.Session()
    img = sess.open(image_path)
    out = img.gaussian(sigma=1.5).image.median(window_size=3).image
    chain = sess.provenance.ancestry(out.id)
    assert [s.op for s in chain] == ["gaussian", "median"]
    assert chain[0].params["sigma"] == 1.5
    assert chain[0].version == __version__
    assert chain[0].timestamp  # stamped

    methods = out.methods()
    assert "scan.emd" in methods
    assert "gaussian (sigma=1.5)" in methods

    parsed = json.loads(out.provenance_json())
    assert [s["op"] for s in parsed] == ["gaussian", "median"]


def test_value_op_records_a_step_with_no_output(image_path) -> None:
    sess = fv.Session()
    img = sess.open(image_path)
    img.image_stats()
    steps = sess.provenance.steps
    stat_steps = [s for s in steps if s.op == "image_stats"]
    assert len(stat_steps) == 1
    assert stat_steps[0].output is None
    assert stat_steps[0].value["shape"] == [6, 8]
