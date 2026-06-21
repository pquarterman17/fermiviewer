"""Public Python surface fermiviewer.api (Scripting #2): the façade loads,
runs ops, chains derived images, and never reaches into the server stack."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import fermiviewer.api as fv
from fermiviewer.calc import filters
from fixtures.miniemd import write_ncem_emd

pytestmark = pytest.mark.parser


@pytest.fixture()
def image_path(tmp_path) -> Path:
    img = np.arange(8 * 10, dtype=np.float32).reshape(8, 10)
    return write_ncem_emd(
        tmp_path / "scan.emd",
        img,
        [(np.arange(8) * 0.5, "y", "nm"), (np.arange(10) * 0.5, "x", "nm")],
    )


def test_open_returns_an_image(image_path) -> None:
    img = fv.open(image_path)
    assert isinstance(img, fv.Image)
    assert img.kind == "image"
    assert img.shape == (8, 10)
    assert img.pixel_unit == "nm"
    assert img.pixel_size == pytest.approx(0.5)
    assert "Image" in repr(img)


def test_op_method_matches_the_calc_path(image_path) -> None:
    img = fv.open(image_path)
    result = img.gaussian(sigma=2.0)
    assert isinstance(result, fv.Result)
    derived = result.image
    assert isinstance(derived, fv.Image)
    expected = filters.apply_gaussian(img.to_numpy().astype(np.float64), sigma=2.0)
    assert np.allclose(derived.to_numpy(), expected)
    assert result.params["sigma"] == 2.0


def test_value_op_returns_value_not_image(image_path) -> None:
    img = fv.open(image_path)
    result = img.image_stats()
    assert result.image is None
    assert result.value["shape"] == [8, 10]
    assert result.value["max"] == float(img.to_numpy().max())


def test_pipeline_chains_through_derived_images(image_path) -> None:
    img = fv.open(image_path)
    out = img.gaussian(sigma=1.0).image.median(window_size=3).image
    assert isinstance(out, fv.Image)
    assert out.shape == (8, 10)


def test_run_by_name_and_unknown_op(image_path) -> None:
    img = fv.open(image_path)
    assert img.run("rotate90").image.shape == (10, 8)
    with pytest.raises(AttributeError):
        _ = img.no_such_op  # __getattr__ rejects unknown ops


def test_ops_catalogue_is_listable() -> None:
    names = {o["name"] for o in fv.ops()}
    assert {"gaussian", "median", "image_stats"} <= names


def test_public_all_is_stable() -> None:
    # the documented surface is the semver contract — pin it
    assert set(fv.__all__) == {"Image", "Result", "Session", "open", "ops"}


def test_session_tracks_opened_and_derived_images(image_path) -> None:
    sess = fv.Session()
    img = sess.open(image_path)
    derived = img.gaussian(sigma=1.0).image
    assert img.id in sess.images
    assert derived.id in sess.images
    assert len(sess.images) == 2


def test_api_package_never_imports_the_server_stack() -> None:
    # the façade must run headless — scan its sources for forbidden imports
    api_dir = Path(fv.__file__).parent
    forbidden = ("fastapi", "fermiviewer.routes", "starlette", "pydantic")
    for f in api_dir.rglob("*.py"):
        for line in f.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith(("import ", "from ")):
                assert not any(bad in s for bad in forbidden), f"{f.name}: {s}"
