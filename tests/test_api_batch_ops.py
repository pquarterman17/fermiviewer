from __future__ import annotations

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.eds import line_energy
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.jobs import JobQueueFullError, jobs
from fermiviewer.server import create_app
from fermiviewer.session import store

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _image(name: str, offset: float = 0) -> str:
    data = np.arange(64 * 64, dtype=np.float64).reshape(64, 64) + offset
    ds = DataStruct(
        data=data,
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0, "nm"), AxisCal(0.5, 0, "nm")),
        metadata={"source": name},
    )
    return store.add_parsed(ds, name)


def _eds_cube(name: str) -> tuple[str, float]:
    """A small SI cube with a single Fe Ka peak (energy from the app's own
    line_energy() table, per the fixtures-derive-from-production-tables
    convention)."""
    ny, nx, ne = 6, 6, 800
    scale = 0.015
    energy_kev = np.arange(ne) * scale                    # 0 – 11.985 keV
    fe_e, _ = line_energy("Fe", beam_kv=200.0)
    spectrum = np.full(ne, 3.0)
    spectrum += 80.0 * np.exp(-((energy_kev - fe_e) ** 2) / (2 * 0.03**2))
    cube = np.tile(spectrum, (ny, nx, 1))
    ds = DataStruct(
        data=cube, kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(1.0, 0, "nm"), AxisCal(1.0, 0, "nm"), AxisCal(scale, 0, "keV")),
        metadata={"source": name},
    )
    return store.add_parsed(ds, name), float(fe_e)


def _poll(client, job_id: str, timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.01)
    raise AssertionError("batch job did not finish")


def test_batch_operation_schema_exposes_analysis_and_filters(client) -> None:
    response = client.get("/api/batch/operations")
    assert response.status_code == 200
    operations = {item["name"]: item for item in response.json()["operations"]}
    assert {
        "gaussian", "plane_level", "morph", "multiotsu",
        "image_stats", "noise", "roughness",
    } <= operations.keys()
    assert operations["noise"]["produces"] == "analysis"
    method = operations["noise"]["params"][0]
    assert method["choices"] == ["mad", "localvar", "both"]


def test_batch_operation_schema_exposes_spectral_ops(client) -> None:
    response = client.get("/api/batch/operations")
    operations = {item["name"]: item for item in response.json()["operations"]}
    assert {
        "eels_map", "eels_quantify", "eds_element_map", "eds_quantify",
        "radial_profile",
    } <= operations.keys()
    # value-producing ops report produces="analysis" even in a non-"analysis"
    # category (eels/eds/diffraction) — the schema-time hint added alongside
    # this catalogue, since category alone used to decide it
    assert operations["eels_quantify"]["produces"] == "analysis"
    assert operations["eds_quantify"]["produces"] == "analysis"
    assert operations["radial_profile"]["produces"] == "analysis"
    assert operations["eels_map"]["produces"] == "image"
    assert operations["eds_element_map"]["produces"] == "image"
    assert operations["eels_map"]["category"] == "eels"
    assert operations["eds_quantify"]["category"] == "eds"
    assert operations["radial_profile"]["category"] == "diffraction"


def test_batch_recipe_produces_images_and_values(client) -> None:
    first = _image("first.dm4")
    second = _image("second.dm4", 10)
    response = client.post("/api/batch/run", json={
        "image_ids": [first, second],
        "steps": [
            {"op": "gaussian", "params": {"sigma": 1}},
            {"op": "image_stats", "params": {}},
            {"op": "noise", "params": {"method": "both"}},
        ],
    })
    assert response.status_code == 200, response.text
    final = _poll(client, response.json()["job_id"])
    assert final["status"] == "done"
    result = final["result"]
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert len(result["outputs"]) == 2
    for output in result["outputs"]:
        assert output["status"] == "done"
        assert [value["op"] for value in output["values"]] == [
            "image_stats", "noise",
        ]
        derived_id = output["derived"]["id"]
        assert client.get(f"/api/image/{derived_id}/render").status_code == 200


def test_batch_recipe_mixes_eds_ops_with_filters_and_values(client) -> None:
    """A recipe mixing a new EDS quant/map op with the pre-existing filter
    and analysis ops (Scripting #6, remaining half): quantify the Fe peak
    (value, runs against the raw cube), extract its element map (image,
    still against the raw cube since quantify doesn't alter the chain),
    smooth it with an existing filter op, then collect image stats. A
    plain 2D image can't satisfy the EDS ops' spectrum-image requirement,
    so it exercises per-input failure isolation too."""
    good, fe_e = _eds_cube("good.bcf")
    bad = _image("not-a-cube.dm4")
    response = client.post("/api/batch/run", json={
        "image_ids": [good, bad],
        "steps": [
            {"op": "eds_quantify", "params": {"elements": "Fe"}},
            {"op": "eds_element_map", "params": {
                "e_lo": fe_e - 0.1, "e_hi": fe_e + 0.1,
            }},
            {"op": "gaussian", "params": {"sigma": 1.0}},
            {"op": "image_stats", "params": {}},
        ],
    })
    assert response.status_code == 200, response.text
    final = _poll(client, response.json()["job_id"])
    assert final["status"] == "done"
    result = final["result"]
    assert result["succeeded"] == 1
    assert result["failed"] == 1

    good_out = next(o for o in result["outputs"] if o["image_id"] == good)
    assert good_out["status"] == "done"
    assert [v["op"] for v in good_out["values"]] == ["eds_quantify", "image_stats"]
    quant = good_out["values"][0]["value"]
    assert quant["elements"] == ["Fe"]
    assert quant["mean_atomic_pct"][0] == pytest.approx(100.0, abs=1e-6)
    stats = good_out["values"][1]["value"]
    assert stats["shape"] == [6, 6]
    assert good_out["derived"] is not None
    render = client.get(f"/api/image/{good_out['derived']['id']}/render")
    assert render.status_code == 200

    bad_out = next(o for o in result["outputs"] if o["image_id"] == bad)
    assert bad_out["status"] == "error"
    assert "spectrum-image" in bad_out["error"]
    assert bad_out["derived"] is None
    assert bad_out["values"] == []


def test_batch_retains_other_inputs_when_one_operation_fails(client) -> None:
    good = _image("good.dm4")
    too_small = DataStruct(
        data=np.ones((2, 2)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )
    bad = store.add_parsed(too_small, "too-small.dm4")
    response = client.post("/api/batch/run", json={
        "image_ids": [good, bad],
        "steps": [{"op": "bin", "params": {"bin_size": 4}}],
    })
    final = _poll(client, response.json()["job_id"])["result"]
    assert final["succeeded"] == 1
    assert final["failed"] == 1
    assert [item["status"] for item in final["outputs"]] == ["done", "error"]
    assert final["outputs"][0]["derived"] is not None
    assert final["outputs"][1]["error"].startswith("step 1 (bin):")


def test_batch_rejects_bad_recipe_before_queueing(client) -> None:
    image_id = _image("source.dm4")
    response = client.post("/api/batch/run", json={
        "image_ids": [image_id],
        "steps": [{"op": "gaussian", "params": {"sgima": 2}}],
    })
    assert response.status_code == 422
    assert "unknown param" in response.json()["detail"]


def test_batch_rejects_unknown_image_before_queueing(client) -> None:
    response = client.post("/api/batch/run", json={
        "image_ids": ["missing"],
        "steps": [{"op": "image_stats", "params": {}}],
    })
    assert response.status_code == 404


def test_batch_queue_saturation_is_429(client, monkeypatch) -> None:
    image_id = _image("source.dm4")

    def full(_fn):
        raise JobQueueFullError("queue full")

    monkeypatch.setattr(jobs, "submit", full)
    response = client.post("/api/batch/run", json={
        "image_ids": [image_id],
        "steps": [{"op": "image_stats", "params": {}}],
    })
    assert response.status_code == 429
    assert response.json()["detail"] == "queue full"


# ── json_safe: shared batch-result JSON coercion ────────────────────────


def test_json_safe_handles_datetime_timedelta_complex_and_bytes() -> None:
    """These types don't currently flow out of any registered op's
    OpResult.value, but json_safe is the ONE choke point every op's value
    passes through before a job result is considered done — passing one
    of them through unchanged (the old fallback behavior) doesn't fail
    here, it fails much later at actual JSON-response-encoding time with a
    bare "Object of type X is not JSON serializable", far from this
    function and easy to miss in review."""
    import datetime
    import json as jsonlib

    from fermiviewer.routes.batch_ops import json_safe

    assert json_safe(np.datetime64("2020-01-01")) == "2020-01-01"
    assert json_safe(np.timedelta64(5, "D")) == "5 days"
    assert json_safe(datetime.date(2021, 6, 1)) == "2021-06-01"
    assert json_safe(datetime.timedelta(seconds=90)) == 90.0
    assert json_safe(3 + 4j) == {"real": 3.0, "imag": 4.0}
    assert json_safe(np.complex128(1 + 2j)) == {"real": 1.0, "imag": 2.0}
    assert json_safe(b"hello") == "hello"
    assert json_safe(np.bytes_(b"hi")) == "hi"

    nested = {"t": np.datetime64("2021-06-01"), "vals": [1 + 2j, b"x", float("nan")]}
    # every value above must survive an ACTUAL json.dumps, not just
    # json_safe's own return value
    encoded = jsonlib.dumps(json_safe(nested))
    assert jsonlib.loads(encoded) == {
        "t": "2021-06-01", "vals": [{"real": 1.0, "imag": 2.0}, "x", None],
    }


# ── register_final_image: NaN-axis-cal guard ────────────────────────────


def test_register_final_image_with_nan_axis_origin_nulls_energy_bounds() -> None:
    """AxisCal.calibrated only requires a finite, non-zero scale — a NaN
    ORIGIN (finite scale notwithstanding) still produces a NaN-filled
    axis. Left unguarded, energy_first/energy_last would carry that NaN
    into the JSON response as a literal `NaN` token: valid to Python's own
    json.dumps (allow_nan defaults True) but a SyntaxError to the
    frontend's JSON.parse, which fails the ENTIRE response, not just this
    field."""
    import json as jsonlib

    from fermiviewer.routes.batch_ops import register_final_image

    src = DataStruct(
        data=np.ones((2, 2)), kind=DataKind.IMAGE, axes=(AxisCal(), AxisCal()),
    )
    image_id = store.add_parsed(src, "source.png")
    final = DataStruct(
        data=np.ones((2, 2, 5)), kind=DataKind.SPECTRUM_IMAGE,
        axes=(
            AxisCal(1.0, 0.0, "nm"), AxisCal(1.0, 0.0, "nm"),
            AxisCal(1.0, float("nan"), "eV"),  # finite scale, NaN origin
        ),
    )
    out = register_final_image(image_id, "source.png", final, [])

    assert out["energy_first"] is None
    assert out["energy_last"] is None
    assert "NaN" not in jsonlib.dumps(out)


# ── recipe auxiliary inputs (ADR 0005 §8) ─────────────────────────────


def _subtract_recipe() -> list[dict]:
    return [
        {
            "op": "image_math",
            "params": {"op": "subtract"},
            "inputs": {"other": "dark"},
        }
    ]


def test_batch_run_binds_a_named_auxiliary_input(client) -> None:
    subject, dark = _image("scan.dm4"), _image("dark.dm4", offset=3)
    job = client.post(
        "/api/batch/run",
        json={
            "image_ids": [subject],
            "inputs": {"dark": dark},
            "steps": _subtract_recipe(),
        },
    )
    assert job.status_code == 200, job.text
    body = _poll(client, job.json()["job_id"])
    assert body["status"] == "done", body
    result = body["result"]
    assert result["succeeded"] == 1 and result["failed"] == 0
    # the binding is recorded beside the steps: the steps alone no longer
    # describe the computation once one of them names a dataset
    assert result["inputs"] == {"dark": dark}
    derived = result["outputs"][0]["derived"]
    assert derived is not None


def test_batch_run_404s_an_unknown_auxiliary_id_before_queueing(client) -> None:
    subject = _image("scan.dm4")
    response = client.post(
        "/api/batch/run",
        json={
            "image_ids": [subject],
            "inputs": {"dark": "no-such-image"},
            "steps": _subtract_recipe(),
        },
    )
    assert response.status_code == 404
    assert "no-such-image" in response.text


def test_batch_run_422s_a_step_naming_an_unbound_input(client) -> None:
    """The reference is checked against the pool up front — a 200-input
    batch must not start when every input would fail on step 1."""
    subject = _image("scan.dm4")
    response = client.post(
        "/api/batch/run",
        json={"image_ids": [subject], "steps": _subtract_recipe()},
    )
    assert response.status_code == 422
    assert "does not supply" in response.text


def test_batch_run_422s_a_multi_input_op_with_no_inputs_named(client) -> None:
    subject = _image("scan.dm4")
    response = client.post(
        "/api/batch/run",
        json={
            "image_ids": [subject],
            "steps": [{"op": "image_math", "params": {"op": "subtract"}}],
        },
    )
    assert response.status_code == 422
    assert "needs auxiliary input" in response.text


def test_the_palette_no_longer_advertises_recipe_step(client) -> None:
    """It existed for one release to mean "not scriptable"; every op is a
    recipe step now, so the flag is gone rather than permanently true."""
    ops_by_name = {
        op["name"]: op
        for op in client.get("/api/batch/operations").json()["operations"]
    }
    assert "recipe_step" not in ops_by_name["image_math"]
    assert [i["name"] for i in ops_by_name["image_math"]["inputs"]] == ["other"]


def test_a_queued_batch_uses_the_pool_resolved_at_submit(client) -> None:
    """The 200 accepted the recipe as runnable; a queue wait can be long,
    and removing an auxiliary image before a worker picks the job up must
    not turn that acceptance into a failure.

    The store has no per-id delete, so the whole store is cleared and the
    subject re-added — the subject is re-read per input by design, only the
    auxiliary pool is snapshotted."""
    from fermiviewer.routes.batch_ops import _run_batch, resolve_recipe_inputs

    dark = _image("dark.dm4", offset=3)
    pool = resolve_recipe_inputs({"dark": dark})  # what /batch/run closes over

    store.clear()
    subject = _image("scan.dm4")

    result = _run_batch(
        [subject], _subtract_recipe(), lambda *_: None, pool, {"dark": dark}
    )

    assert result["succeeded"] == 1, result
    assert result["inputs"] == {"dark": dark}  # the id binding is still recorded


def test_a_watch_run_uses_the_pool_resolved_at_start(tmp_path) -> None:
    """A watch runs for hours; every file it picks up must see the reference
    data bound at /watch/start, not whatever the store holds later."""
    import numpy as np
    from PIL import Image as PILImage

    from fermiviewer.routes.batch_ops import resolve_recipe_inputs
    from fermiviewer.routes.watch import _run_watch_job

    dark = _image("dark.dm4", offset=3)
    pool = resolve_recipe_inputs({"dark": dark})  # what /watch/start closes over

    path = tmp_path / "incoming.png"
    PILImage.fromarray(np.full((8, 8), 7, dtype=np.uint8)).save(path, format="PNG")

    store.clear()  # the auxiliary image is deleted after the watch started
    body = _run_watch_job(
        path, _subtract_recipe(), lambda *_: None, pool, {"dark": dark}
    )
    assert body["derived"] is not None


# ── named regions over the HTTP boundary (4C-5) ──────────────────────


def _region_set(image_id: str | None = None, half: bool = False):
    """A set holding one rect region: the left half, or the whole image."""
    from fermiviewer.calc.regions import Part, Region, Shape
    from fermiviewer.io.regions_model import RegionSet

    bounds = (0.0, 0.0, 63.0, 31.0) if half else (0.0, 0.0, 63.0, 63.0)
    return RegionSet(
        id="s1",
        regions=(Region(id="r1", parts=(Part(Shape(kind="rect", bounds=bounds)),)),),
        image_id=image_id,
    )


def _stats_value(output: dict) -> dict:
    return next(v for v in output["values"] if v["op"] == "image_stats")


def test_a_named_region_survives_the_http_boundary_and_changes_the_answer(
    client,
) -> None:
    """The end-to-end test this feature was missing.

    Every 4C-5 test called `substitute_region_refs` or `ops.run` directly,
    so none of them touched the request model — where `region_ref` was
    being silently dropped by pydantic, leaving the op to run over the
    whole image. A number that differs from the whole-image one is the
    only assertion that could have caught that, because the shape of the
    response is identical either way.
    """
    from fermiviewer.project_session import project

    image_id = _image("scoped.dm4")
    project.current()  # ensure a live project
    project.replace_regions((_region_set(half=True),), ())

    def run(step: dict) -> dict:
        response = client.post(
            "/api/batch/run", json={"image_ids": [image_id], "steps": [step]}
        )
        assert response.status_code == 200, response.text
        final = _poll(client, response.json()["job_id"])
        assert final["status"] == "done", final
        output = final["result"]["outputs"][0]
        assert output["status"] == "done", output
        return _stats_value(output)

    named = run({"op": "image_stats", "region_ref": "s1/r1"})
    whole = run({"op": "image_stats"})

    assert named["value"]["mean"] != whole["value"]["mean"], (
        "the named region must actually scope the op"
    )
    assert named["value"]["n_finite"] == 64 * 32
    assert whole["value"]["n_finite"] == 64 * 64
    # ADR 0005: the RECORDED params are the replay key, so they carry the
    # resolved geometry and no longer mention the set by name
    assert named["params"]["region"], "resolved geometry must be recorded"
    assert "s1" not in repr(named["params"])
    assert named["value"]["region"]["rows"] == [[1, 1, 64, 32]]


def test_an_unknown_region_reference_is_refused_before_the_job_is_queued(
    client,
) -> None:
    image_id = _image("typo.dm4")
    response = client.post(
        "/api/batch/run",
        json={
            "image_ids": [image_id],
            "steps": [{"op": "image_stats", "region_ref": "nope/r1"}],
        },
    )
    assert response.status_code == 422, response.text


def test_a_region_bound_to_another_image_skips_that_input_with_a_reason(
    client,
) -> None:
    """The per-image policy, asserted through the API: the batch does not
    fail, the bound image is skipped, and the reason names the image."""
    from fermiviewer.project_session import project

    mine = _image("mine.dm4")
    other = _image("other.dm4", 10)
    project.current()
    project.replace_regions((_region_set(image_id=mine, half=True),), ())

    response = client.post(
        "/api/batch/run",
        json={
            "image_ids": [mine, other],
            "steps": [{"op": "image_stats", "region_ref": "s1/r1"}],
        },
    )
    assert response.status_code == 200, response.text
    final = _poll(client, response.json()["job_id"])
    outputs = {o["image_id"]: o for o in final["result"]["outputs"]}
    assert outputs[mine]["status"] == "done"
    assert outputs[other]["status"] == "error"
    assert other in outputs[other]["error"], outputs[other]["error"]
    assert final["result"]["succeeded"] == 1
    assert final["result"]["failed"] == 1


def test_region_sets_are_snapshotted_when_the_job_is_accepted(
    client, monkeypatch
) -> None:
    """A 200 from `/batch/run` is a promise about what will run.

    `_run_batch` is the job BODY, so reading the region sets there would
    let an edit made after the 200 — but before a worker picks the job up
    — change which pixels the accepted recipe measures. The job function
    is captured here instead of racing the queue, so the window between
    accept and start is opened deliberately rather than hoped for.
    """
    from fermiviewer.project_session import project
    from fermiviewer.routes import batch_ops

    image_id = _image("snapshot.dm4")
    project.current()
    project.replace_regions((_region_set(half=True),), ())

    captured: list = []
    monkeypatch.setattr(
        batch_ops.jobs, "submit", lambda fn: (captured.append(fn), "job-1")[1]
    )
    response = client.post(
        "/api/batch/run",
        json={
            "image_ids": [image_id],
            "steps": [{"op": "image_stats", "region_ref": "s1/r1"}],
        },
    )
    assert response.status_code == 200, response.text

    # the edit lands in the window between accept and start
    project.replace_regions((_region_set(half=False),), ())

    result = captured[0](lambda *_a, **_k: None)
    stats = _stats_value(result["outputs"][0])
    assert stats["value"]["n_finite"] == 64 * 32, (
        "the accepted half-image region, not the edited whole-image one"
    )
