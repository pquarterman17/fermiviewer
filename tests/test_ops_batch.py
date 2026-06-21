"""Recipe runner (Scripting #6): chaining image steps, collecting value
steps, validation, and the façade Image.pipeline with provenance."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import fermiviewer.api as fv
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops.batch import run_recipe, validate_recipe
from fixtures.miniemd import write_ncem_emd

pytestmark = pytest.mark.parser


def _image(h: int = 8, w: int = 8) -> DataStruct:
    return DataStruct(
        data=np.arange(h * w, dtype=np.float64).reshape(h, w),
        kind=DataKind.IMAGE,
        axes=(AxisCal(1.0, 0.0, "nm"), AxisCal(1.0, 0.0, "nm")),
    )


def test_run_recipe_chains_image_steps() -> None:
    ds = _image(8, 8)
    recipe = [
        {"op": "gaussian", "params": {"sigma": 1.0}},
        {"op": "bin", "params": {"bin_size": 2}},
    ]
    out = run_recipe(ds, recipe)
    assert len(out.steps) == 2
    assert out.final.data.shape == (4, 4)  # binned final image
    assert out.values == []  # no value-producing steps


def test_run_recipe_collects_value_steps_without_breaking_chain() -> None:
    ds = _image(8, 8)
    recipe = [
        {"op": "gaussian", "params": {"sigma": 1.0}},
        {"op": "image_stats"},  # value step — runs on the blurred image
        {"op": "rotate90"},
    ]
    out = run_recipe(ds, recipe)
    assert out.final.data.shape == (8, 8)  # rotate keeps dims square
    assert len(out.values) == 1
    assert out.values[0].op == "image_stats"
    assert out.values[0].value["shape"] == [8, 8]


def test_validate_recipe_rejects_malformed_steps() -> None:
    with pytest.raises(ValueError, match="'op' key"):
        validate_recipe([{"params": {}}])
    with pytest.raises(ValueError, match="must be a string"):
        validate_recipe([{"op": 5}])


@pytest.fixture()
def image_path(tmp_path) -> Path:
    img = np.arange(64, dtype=np.float32).reshape(8, 8)
    return write_ncem_emd(
        tmp_path / "scan.emd",
        img,
        [(np.arange(8) * 1.0, "y", "nm"), (np.arange(8) * 1.0, "x", "nm")],
    )


def test_facade_pipeline_records_provenance(image_path) -> None:
    img = fv.open(image_path)
    results = img.pipeline(
        [
            {"op": "gaussian", "params": {"sigma": 1.0}},
            {"op": "median", "params": {"window_size": 3}},
        ]
    )
    assert len(results) == 2
    final = results[-1].image
    chain = [s.op for s in img._session.provenance.ancestry(final.id)]
    assert chain == ["gaussian", "median"]
