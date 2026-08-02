"""``fv --script`` headless recipe runner (Scripting #10): recipe loading
(bare + .fvbatch.json preset export), op/param validation before any input
is touched, input expansion (files/dirs/globs), per-input output writing
(TIFF/CSV/JSON/provenance), per-input failure isolation, and the argparse
wiring in server.main() that must never start the server or open a browser.
"""

from __future__ import annotations

import io
import json
import sys
import webbrowser
from pathlib import Path

import numpy as np
import pytest
import tifffile
import uvicorn

from fermiviewer import cli_script, server
from fermiviewer.cli_script import run_script

pytestmark = pytest.mark.api


def _write_png(path: Path, value: int = 5, size: int = 8) -> Path:
    from PIL import Image

    Image.fromarray(np.full((size, size), value, dtype=np.uint8)).save(path, format="PNG")
    return path


def _bare_recipe(path: Path, steps: list[dict], name: str | None = None) -> Path:
    payload: dict = {"steps": steps}
    if name is not None:
        payload["name"] = name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fvbatch_preset(path: Path, steps: list[dict], name: str) -> Path:
    """The exact shape BatchDialog's export button writes
    (batchRecipePresets.ts's exportBatchRecipePreset)."""
    payload = {
        "format": "fermiviewer-batch-preset",
        "version": 1,
        "preset": {
            "version": 1,
            "id": "11111111-1111-1111-1111-111111111111",
            "name": name,
            "steps": steps,
            "createdAt": "2026-01-01T00:00:00+00:00",
            "updatedAt": "2026-01-01T00:00:00+00:00",
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ── happy path: image op + value op, one input ─────────────────────────


def test_run_script_writes_tiff_table_and_provenance(tmp_path: Path) -> None:
    img_path = _write_png(tmp_path / "sample.png")
    recipe_path = _bare_recipe(
        tmp_path / "recipe.json",
        [
            {"op": "gaussian", "params": {"sigma": 1.0}},
            {"op": "image_stats", "params": {}},
        ],
    )
    out_dir = tmp_path / "out"
    buf = io.StringIO()

    code = run_script(recipe_path, [str(img_path)], out_dir, stdout=buf)

    assert code == 0
    # no recipe name given -> falls back to the op that produced the final
    # image (gaussian, since image_stats never advances the chain)
    tif_path = out_dir / "sample.gaussian.tif"
    assert tif_path.is_file()
    written = tifffile.imread(tif_path)
    assert written.dtype == np.float32
    assert written.shape == (8, 8)
    # image_stats() ran against the ALREADY-blurred image (pipeline chaining)
    # — compare against the actual written raster, not the pre-blur value,
    # so this doesn't assume anything about gaussian's boundary handling.
    expected_mean = float(np.asarray(written, dtype=np.float64).mean())

    csv_path = out_dir / "sample.image_stats.csv"
    json_path = out_dir / "sample.image_stats.json"
    assert csv_path.is_file() and json_path.is_file()
    csv_text = csv_path.read_text(encoding="utf-8")
    header = csv_text.splitlines()[0]
    assert {"mean", "std", "min", "max", "shape"} <= set(header.split(","))
    json_body = json.loads(json_path.read_text(encoding="utf-8"))
    assert json_body["columns"] == ["mean", "std", "min", "max", "shape"]
    assert json_body["rows"][0]["mean"] == pytest.approx(expected_mean, abs=1e-3)

    provenance_path = out_dir / "sample.provenance.json"
    assert provenance_path.is_file()
    steps_logged = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert [s["op"] for s in steps_logged] == ["gaussian", "image_stats"]

    methods_path = out_dir / "sample.methods.md"
    assert methods_path.is_file()
    assert "gaussian" in methods_path.read_text(encoding="utf-8")

    summary = buf.getvalue()
    assert "OK    " in summary
    assert "1/1 succeeded, 0 failed" in summary


def test_fvbatch_preset_export_runs_unchanged(tmp_path: Path) -> None:
    """A recipe saved through the GUI's export button runs headlessly with
    no translation step."""
    img_path = _write_png(tmp_path / "scan.png")
    recipe_path = _fvbatch_preset(
        tmp_path / "my-recipe.fvbatch.json",
        [{"op": "gaussian", "params": {"sigma": 1.0}}],
        name="My Recipe",
    )
    out_dir = tmp_path / "out"

    code = run_script(recipe_path, [str(img_path)], out_dir)

    assert code == 0
    assert (out_dir / "scan.my-recipe.tif").is_file()


# ── recipe validation happens before any input is touched ──────────────


def test_unknown_op_exits_2_before_touching_inputs(tmp_path: Path) -> None:
    img_path = _write_png(tmp_path / "sample.png")
    recipe_path = _bare_recipe(
        tmp_path / "recipe.json", [{"op": "no_such_op", "params": {}}]
    )
    out_dir = tmp_path / "out"
    buf = io.StringIO()

    code = run_script(recipe_path, [str(img_path)], out_dir, stdout=buf)

    assert code == 2
    assert not out_dir.exists()  # nothing was touched
    assert "error:" in buf.getvalue()


def test_malformed_recipe_json_exits_2(tmp_path: Path) -> None:
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text("{not json", encoding="utf-8")
    out_dir = tmp_path / "out"

    code = run_script(recipe_path, [str(tmp_path)], out_dir)

    assert code == 2
    assert not out_dir.exists()


def test_no_matching_inputs_exits_2(tmp_path: Path) -> None:
    recipe_path = _bare_recipe(
        tmp_path / "recipe.json", [{"op": "image_stats", "params": {}}]
    )
    out_dir = tmp_path / "out"

    code = run_script(recipe_path, [str(tmp_path / "nothing-here-*.png")], out_dir)

    assert code == 2
    assert not out_dir.exists()


# ── directory input expansion ───────────────────────────────────────────


def test_directory_input_expands_to_openable_files(tmp_path: Path) -> None:
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    _write_png(in_dir / "a.png", value=1)
    _write_png(in_dir / "b.png", value=2)
    (in_dir / "notes.txt").write_text("not an image", encoding="utf-8")

    recipe_path = _bare_recipe(
        tmp_path / "recipe.json", [{"op": "image_stats", "params": {}}]
    )
    out_dir = tmp_path / "out"
    buf = io.StringIO()

    code = run_script(recipe_path, [str(in_dir)], out_dir, stdout=buf)

    assert code == 0
    assert (out_dir / "a.image_stats.csv").is_file()
    assert (out_dir / "b.image_stats.csv").is_file()
    # a value-only recipe produces no image -> no TIFF, no methods paragraph
    assert not list(out_dir.glob("*.tif"))
    assert not list(out_dir.glob("*.methods.md"))
    # the provenance log is still written even with no image steps
    assert (out_dir / "a.provenance.json").is_file()
    assert "2/2 succeeded, 0 failed" in buf.getvalue()


# ── per-input failure isolation ─────────────────────────────────────────


def test_corrupt_input_isolated_good_output_still_written(tmp_path: Path) -> None:
    good_path = _write_png(tmp_path / "good.png")
    bad_path = tmp_path / "bad.png"
    bad_path.write_bytes(b"not actually a png")

    recipe_path = _bare_recipe(
        tmp_path / "recipe.json", [{"op": "image_stats", "params": {}}]
    )
    out_dir = tmp_path / "out"
    buf = io.StringIO()

    code = run_script(
        recipe_path, [str(good_path), str(bad_path)], out_dir, stdout=buf
    )

    assert code == 1
    assert (out_dir / "good.image_stats.csv").is_file()
    assert not (out_dir / "bad.image_stats.csv").is_file()
    summary = buf.getvalue()
    assert "FAIL  " in summary
    assert "bad.png" in summary
    assert "1/2 succeeded, 1 failed" in summary


# ── server.main() --script wiring never starts the server ──────────────


def test_main_script_mode_never_starts_the_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recipe_path = _bare_recipe(
        tmp_path / "recipe.json", [{"op": "image_stats", "params": {}}]
    )
    img_path = _write_png(tmp_path / "sample.png")
    out_dir = tmp_path / "out"

    calls: list[str] = []

    def fake_run_script(recipe, inputs, out, **_kw):
        calls.append("run_script")
        assert str(recipe_path) == str(recipe)
        assert inputs == [str(img_path)]
        assert str(out) == str(out_dir)
        return 7

    def must_not_be_called(*_args, **_kwargs):
        raise AssertionError("server.main() must not start the server under --script")

    monkeypatch.setattr(cli_script, "run_script", fake_run_script)
    monkeypatch.setattr(server, "_bind", must_not_be_called)
    monkeypatch.setattr(uvicorn, "Server", must_not_be_called)
    monkeypatch.setattr(webbrowser, "open", must_not_be_called)

    monkeypatch.setattr(
        sys,
        "argv",
        ["fermiviewer", "--script", str(recipe_path), str(img_path), "--out", str(out_dir)],
    )

    with pytest.raises(SystemExit) as exc_info:
        server.main()

    assert exc_info.value.code == 7
    assert calls == ["run_script"]
