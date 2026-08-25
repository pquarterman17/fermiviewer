"""The re-opened op contract (ADR 0005 §8–§9): auxiliary ``DataStruct``
inputs and list-shaped params, plus the exemplar ops that exercise them.

Waves A–D bounced fifteen endpoints off two gaps — an op could take only
one dataset (gap 1) and only scalar params (gap 2). These tests pin the
contract that closes them: what the schema accepts, what it refuses, and
that the two call conventions cannot silently drift apart.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

import fermiviewer.ops as ops
from fermiviewer.calc.fourier import fft_mask_inverse
from fermiviewer.calc.stack import align_stack, image_math, mip
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops.base import (
    ANY_SCALAR,
    InputError,
    OpInput,
    OpParam,
    OpResult,
    OpSpec,
    ParamError,
    RecordSpec,
    RowSpec,
)

pytestmark = pytest.mark.parser


def _image(h: int = 8, w: int = 10, offset: float = 0.0) -> DataStruct:
    data = np.arange(h * w, dtype=np.float64).reshape(h, w) + offset
    return DataStruct(
        data=data,
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
        metadata={"source": "synthetic"},
    )


def _spectrum() -> DataStruct:
    return DataStruct(
        data=np.arange(6, dtype=np.float64),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(1.0, 0.0, "eV"),),
    )


# ── gap 2: row-list params ────────────────────────────────────────────


def test_row_list_coerces_real_lists_and_reports_column_names() -> None:
    p = OpParam(list, row=RowSpec(3, columns=("row", "col", "radius")), required=True)
    assert p.coerce("masks", [[1, 2, 3], (4.5, 5, 6)]) == [[1.0, 2.0, 3.0], [4.5, 5.0, 6.0]]
    with pytest.raises(ParamError, match=r"masks\[1\].*expected 3 values.*row/col/radius"):
        p.coerce("masks", [[1, 2, 3], [4, 5]])


def test_row_list_refuses_the_older_csv_spelling() -> None:
    """A delimited string reaching a row list means a caller used a
    pre-contract flattening; splitting it silently would resurrect exactly
    the per-op encoding ADR 0005 §4 forbids."""
    p = OpParam(list, row=RowSpec(2), required=True)
    with pytest.raises(ParamError, match="expected a list, got str"):
        p.coerce("points", "1,2,3,4")


def test_row_list_enforces_row_counts() -> None:
    p = OpParam(list, row=RowSpec(2, min_rows=1, max_rows=2))
    assert len(p.coerce("pts", [[1, 2], [3, 4]])) == 2
    with pytest.raises(ParamError, match="needs at least 1 entry"):
        p.coerce("pts", [])
    with pytest.raises(ParamError, match="at most 2 entries"):
        p.coerce("pts", [[1, 2], [3, 4], [5, 6]])


def test_int_rows_reject_fractional_values() -> None:
    """``int(1.5) == 1`` would address a different pixel than requested —
    the wave-C ``int_group`` rule, now in the contract."""
    p = OpParam(list, row=RowSpec(2, item_type=int))
    assert p.coerce("hkl", [[1, 2], [3.0, 4]]) == [[1, 2], [3, 4]]
    with pytest.raises(ParamError, match="must be a whole number"):
        p.coerce("hkl", [[1, 2.5]])


def test_scalar_int_params_also_reject_fractional_values() -> None:
    """The same rule for plain int params: every route's pydantic int field
    refuses 1.5, so the op layer must not silently truncate it."""
    spec = ops.get_spec("bin")
    with pytest.raises(ParamError, match="must be a whole number"):
        spec.resolve_params({"bin_size": 2.5})
    assert spec.resolve_params({"bin_size": 2.0})["bin_size"] == 2


def test_ragged_and_nullable_rows_are_opt_in() -> None:
    strict = OpParam(list, row=RowSpec(2))
    with pytest.raises(ParamError, match="must not be null"):
        strict.coerce("traces", [None])
    loose = OpParam(list, row=RowSpec(None, allow_none_rows=True))
    assert loose.coerce("traces", [[1, 2, 3], None, [4]]) == [[1.0, 2.0, 3.0], None, [4.0]]


def test_row_items_honour_bounds() -> None:
    p = OpParam(list, row=RowSpec(1), minimum=0.0)
    with pytest.raises(ParamError, match="< min"):
        p.coerce("vals", [[-1.0]])


# ── gap 2: record-list params ─────────────────────────────────────────


def _stroke_param() -> OpParam:
    return OpParam(
        list,
        row=None,
        record=RecordSpec(
            fields={
                "class_id": OpParam(int, required=True, minimum=1),
                "radius": OpParam(float, 4.0),
                "points": OpParam(list, row=RowSpec(2), required=True),
            }
        ),
        required=True,
    )


def test_record_list_fills_defaults_and_nests_one_row_list() -> None:
    got = _stroke_param().coerce("strokes", [{"class_id": 2, "points": [[1, 2], [3, 4]]}])
    assert got == [{"class_id": 2, "radius": 4.0, "points": [[1.0, 2.0], [3.0, 4.0]]}]


def test_record_list_rejects_unknown_and_missing_fields() -> None:
    p = _stroke_param()
    with pytest.raises(ParamError, match="unknown param"):
        p.coerce("strokes", [{"class_id": 1, "points": [], "colour": "red"}])
    with pytest.raises(ParamError, match="missing required 'points'"):
        p.coerce("strokes", [{"class_id": 1}])
    with pytest.raises(ParamError, match="expected an object"):
        p.coerce("strokes", [[1, 2]])


def test_record_field_errors_name_their_position() -> None:
    with pytest.raises(ParamError, match=r"strokes\[1\].class_id"):
        _stroke_param().coerce(
            "strokes",
            [{"class_id": 1, "points": []}, {"class_id": 0, "points": []}],
        )


def test_records_do_not_nest() -> None:
    inner = OpParam(list, record=RecordSpec(fields={"x": OpParam(float)}))
    with pytest.raises(ValueError, match="records do not nest"):
        RecordSpec(fields={"inner": inner})


def test_list_param_shape_is_declared_exactly_once() -> None:
    with pytest.raises(ValueError, match="must declare 'row' or 'record'"):
        OpParam(list)
    with pytest.raises(ValueError, match="either 'row'- or 'record'-shaped"):
        OpParam(list, row=RowSpec(2), record=RecordSpec(fields={}))
    with pytest.raises(ValueError, match="must have ptype=list"):
        OpParam(float, row=RowSpec(2))


def test_any_scalar_accepts_json_scalars_but_not_containers() -> None:
    p = OpParam(ANY_SCALAR)
    for value in (1.5, "auto", True, None, 3):
        assert p.coerce("param_value", value) == value
    with pytest.raises(ParamError, match="expected a number, string, bool or null"):
        p.coerce("param_value", [1, 2])


# ── exclusive bounds (the §4 fidelity gap the addenda recorded) ───────


def test_exclusive_bounds_mirror_the_routes_gt_lt_fields() -> None:
    p = OpParam(float, 0.5, exclusive_minimum=0.0, exclusive_maximum=1.0)
    assert p.coerce("overlap", 0.5) == 0.5
    with pytest.raises(ParamError, match="must be > 0.0"):
        p.coerce("overlap", 0.0)
    with pytest.raises(ParamError, match="must be < 1.0"):
        p.coerce("overlap", 1.0)


def test_ctf_pixel_size_now_carries_the_bound_in_the_schema() -> None:
    """It used to be a hand-written ValueError in the op fn (wave B)."""
    with pytest.raises(ParamError, match="must be > 0"):
        ops.get_spec("ctf").resolve_params({"pixel_size_a": 0.0})


# ── gap 1: auxiliary inputs ───────────────────────────────────────────


def test_declared_inputs_are_required_checked_and_kind_checked() -> None:
    a, b = _image(), _image(offset=3)
    with pytest.raises(InputError, match="missing required input 'other'"):
        ops.run("image_math", a)
    with pytest.raises(InputError, match=r"unknown input\(s\) \['nope'\]"):
        ops.run("image_math", a, inputs={"nope": b})
    with pytest.raises(InputError, match="expected a DataStruct"):
        ops.run("image_math", a, inputs={"other": [b]})
    with pytest.raises(InputError, match="kind spectrum not in"):
        ops.run("image_math", a, inputs={"other": _spectrum()})


def test_variadic_inputs_check_their_count() -> None:
    a = _image()
    with pytest.raises(InputError, match="expected a list of datasets"):
        ops.run("mip", a, inputs={"others": _image()})
    with pytest.raises(InputError, match="needs at least 1 dataset"):
        ops.run("mip", a, inputs={"others": []})


def test_a_single_subject_op_refuses_auxiliary_inputs() -> None:
    """Silently ignoring them would run a different computation than asked."""
    with pytest.raises(InputError, match="takes no auxiliary inputs"):
        ops.run("gaussian", _image(), {"sigma": 1.0}, inputs={"other": _image()})


def test_every_registered_fn_matches_its_declared_arity() -> None:
    """The call convention follows the schema — a spec with ``inputs`` gets
    ``fn(ds, params, inputs)``, everything else ``fn(ds, params)``. This is
    the guard that keeps the two conventions from drifting."""
    for spec in ops.list_ops():
        positional = [
            p
            for p in inspect.signature(spec.fn).parameters.values()
            if p.kind
            in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        expected = 3 if spec.multi_input else 2
        assert len(positional) == expected, (
            f"op '{spec.name}' declares "
            f"{'auxiliary inputs' if spec.multi_input else 'no inputs'} but its "
            f"fn takes {len(positional)} positional args (expected {expected})"
        )


def test_a_multi_input_step_must_name_its_auxiliary_inputs() -> None:
    """A recipe step CAN carry a multi-input op now, but only by naming the
    datasets it needs — an unnamed required input fails at validation rather
    than halfway through a long run."""
    from fermiviewer.ops.batch import validate_recipe

    with pytest.raises(ValueError, match="needs auxiliary input"):
        validate_recipe([{"op": "gaussian"}, {"op": "image_math"}], ["dark"])
    # named and bound: accepted
    validate_recipe(
        [{"op": "image_math", "inputs": {"other": "dark"}}], ["dark"]
    )


def test_recipe_input_references_are_checked_against_the_pool() -> None:
    from fermiviewer.ops.batch import validate_recipe

    step = [{"op": "image_math", "inputs": {"other": "dark"}}]
    with pytest.raises(ValueError, match="does not supply"):
        validate_recipe(step, [])  # nothing bound
    with pytest.raises(ValueError, match="does not supply"):
        validate_recipe(step, ["flat"])  # a different name bound
    with pytest.raises(ValueError, match="has no auxiliary input"):
        validate_recipe([{"op": "image_math", "inputs": {"nope": "dark"}}], ["dark"])
    with pytest.raises(ValueError, match="has no auxiliary input"):
        validate_recipe([{"op": "gaussian", "inputs": {"other": "dark"}}], ["dark"])


def test_recipe_binds_the_pool_and_runs_a_multi_input_step() -> None:
    from fermiviewer.ops.batch import run_recipe

    subject, dark = _image(), _image(offset=3)
    result = run_recipe(
        subject,
        [{"op": "image_math", "params": {"op": "subtract"}, "inputs": {"other": "dark"}}],
        inputs={"dark": dark},
    )
    np.testing.assert_allclose(
        result.final.data, image_math(subject.data, dark.data, "subtract")
    )


def test_a_recipe_chains_a_multi_input_step_onto_the_derived_image() -> None:
    """The subject keeps chaining; only the auxiliary input comes from the
    pool, so the pool is NOT re-bound to each step's output."""
    from fermiviewer.ops.batch import run_recipe

    subject, dark = _image(), _image(offset=3)
    result = run_recipe(
        subject,
        [
            {"op": "gaussian", "params": {"sigma": 1.0}},
            {"op": "image_math", "params": {"op": "subtract"}, "inputs": {"other": "dark"}},
        ],
        inputs={"dark": dark},
    )
    blurred = result.steps[0].derived
    np.testing.assert_allclose(
        result.final.data, image_math(blurred.data, dark.data, "subtract")
    )


# ── the exemplar ops run the same calc path as their routes ───────────


def test_image_math_matches_the_calc_function() -> None:
    a, b = _image(), _image(offset=3)
    result = ops.run("image_math", a, {"op": "subtract"}, inputs={"other": b})
    expected = image_math(a.data, b.data, "subtract")
    np.testing.assert_allclose(result.derived.data, expected)
    assert result.derived.axes == (a.axes[0], a.axes[1])  # subject's calibration


def test_mip_matches_the_calc_function() -> None:
    frames = [_image(), _image(offset=3), _image(offset=-5)]
    result = ops.run("mip", frames[0], inputs={"others": frames[1:]})
    expected = mip([f.data for f in frames])
    np.testing.assert_allclose(result.derived.data, expected)


def test_align_stack_inlines_the_movers_and_their_shifts() -> None:
    frames = [_image(), _image(offset=3)]
    result = ops.run("align_stack", frames[0], inputs={"others": frames[1:]})
    expected, shifts = align_stack([f.data for f in frames])
    outputs = {o["name"]: o for o in result.value["outputs"]}
    assert set(outputs) == {"aligned_1", "shifts"}
    np.testing.assert_allclose(outputs["aligned_1"]["data"]["values"], expected[1])
    assert outputs["shifts"]["data"]["rows"][1][1:] == list(shifts[1])
    assert result.derived is None  # N-1 maps exceed the single derived slot


def test_fft_mask_matches_the_calc_function() -> None:
    ds = _image()
    masks = [[4.0, 5.0, 2.0]]
    result = ops.run("fft_mask", ds, {"masks": masks, "mode": "reject"})
    expected = fft_mask_inverse(ds.data, [(4.0, 5.0, 2.0)], mode="reject")
    np.testing.assert_allclose(result.derived.data, expected)


def test_fft_mask_requires_at_least_one_mask() -> None:
    with pytest.raises(ParamError, match="needs at least 1 entry"):
        ops.run("fft_mask", _image(), {"masks": []})


# ── the resolved schema reaches the palette + provenance ──────────────


def test_resolved_params_stay_json_shaped_for_provenance() -> None:
    import json

    result = ops.run("fft_mask", _image(), {"masks": [[4, 5, 2]]})
    assert json.loads(json.dumps(result.params)) == {
        "masks": [[4.0, 5.0, 2.0]],
        "mode": "pass",
    }


def test_optional_inputs_default_to_empty_rather_than_erroring() -> None:
    def _fn(ds: DataStruct, params: dict, inputs: dict) -> OpResult:
        return OpResult(op="t", params=params, label="t", value={"n": len(inputs["extra"])})

    spec = OpSpec(
        name="_contract_probe",
        category="analysis",
        fn=_fn,
        inputs={"extra": OpInput(required=False, variadic=True, min_count=0)},
    )
    assert spec.resolve_inputs(None) == {"extra": []}
    assert spec.resolve_inputs({"extra": None}) == {"extra": []}


# ── the façade and the palette speak the contract ─────────────────────


def _session_with_images() -> tuple:
    import fermiviewer.api as fv

    session = fv.Session()
    a = session._adopt(_image(), "a.dm4")
    b = session._adopt(_image(offset=3), "b.dm4")
    return session, a, b


def test_python_api_takes_images_as_keyword_inputs() -> None:
    session, a, b = _session_with_images()
    result = a.image_math(other=b, op="subtract")
    np.testing.assert_allclose(
        result.image.to_numpy(), image_math(a.datastruct.data, b.datastruct.data, "subtract")
    )
    step = session.provenance.steps[-1]
    assert step.inputs == (a.id, b.id)  # every contributor recorded, not just the subject
    assert step.input_names == ("a.dm4", "b.dm4")


def test_the_op_name_cannot_collide_with_a_param_called_op() -> None:
    """``image_math`` mirrors its route, whose arithmetic selector is ``op``
    — the same word ``Image.run`` uses for the operation name."""
    _, a, b = _session_with_images()
    assert a.image_math(other=b, op="add").image is not None
    assert a.run("image_math", other=b, op="add").image is not None


def test_methods_paragraph_names_the_other_input() -> None:
    """`ancestry` walks the primary spine; a second dataset must not vanish
    from the methods text just because the lineage is a DAG."""
    session, a, b = _session_with_images()
    result = a.image_math(other=b, op="subtract")
    assert "with b.dm4" in session.provenance.to_markdown(result.image.id)


def test_batch_palette_publishes_input_and_shape_schemas() -> None:
    from fermiviewer.routes.batch_ops import batch_operations

    palette = {op["name"]: op for op in batch_operations()["operations"]}

    math_op = palette["image_math"]
    assert math_op["inputs"] == [
        {
            "name": "other",
            "required": True,
            "variadic": False,
            "min_count": None,
            "max_count": None,
            "kinds": ["image", "rgb_image", "spectrum_image"],
            "doc": math_op["inputs"][0]["doc"],
        }
    ]

    masks = next(p for p in palette["fft_mask"]["params"] if p["name"] == "masks")
    assert masks["type"] == "list[3 x row/col/radius]"
    assert masks["shape"]["kind"] == "rows"
    assert masks["shape"]["columns"] == ["row", "col", "radius"]
    assert masks["shape"]["min_rows"] == 1

    assert palette["gaussian"]["inputs"] == []
    # `recipe_step` is gone: it existed only to say "not scriptable", which
    # is no longer true of any op now that recipe steps can name inputs
    assert "recipe_step" not in math_op


def test_facade_rejects_raw_datastructs_without_touching_the_session() -> None:
    """The façade records provenance by image id, so a raw DataStruct has no
    identity to record. It used to reach the recording and raise
    AttributeError — AFTER the derived image had been adopted, leaving an
    orphan in the session with no step. Validation now happens before the op
    runs, so a rejected input cannot mutate anything."""
    session, a, b = _session_with_images()
    raw = _image(offset=9)

    for kwargs in ({"other": raw}, {"other": b, "op": "nope"}):
        images_before = dict(session.images)
        steps_before = len(session.provenance.steps)
        with pytest.raises((TypeError, ValueError)):
            a.image_math(**kwargs)
        assert session.images == images_before, "a failed call adopted an image"
        assert len(session.provenance.steps) == steps_before


def test_facade_rejects_a_raw_datastruct_inside_a_variadic_input() -> None:
    session, a, b = _session_with_images()
    images_before = dict(session.images)
    with pytest.raises(TypeError, match=r"input 'others'.*expected an Image"):
        a.mip(others=[b, _image(offset=9)])
    assert session.images == images_before


def test_raw_datastructs_still_run_through_the_pure_entry_point() -> None:
    """The rejection is about provenance identity, not about the op — the
    pure layer takes structs and records nothing."""
    a, b = _image(), _image(offset=3)
    result = ops.run("image_math", a, {"op": "add"}, inputs={"other": b})
    np.testing.assert_allclose(result.derived.data, image_math(a.data, b.data, "add"))


def test_facade_rejects_images_from_another_session() -> None:
    """An image id is only meaningful inside the session that issued it.
    A cross-session input used to record a parent this session cannot
    resolve — provenance that reads fine and cannot be reopened."""
    import fermiviewer.api as fv

    session, a, b = _session_with_images()
    other_session = fv.Session()
    foreign = other_session._adopt(_image(offset=9), "foreign.dm4")

    images_before = dict(session.images)
    steps_before = len(session.provenance.steps)

    with pytest.raises(ValueError, match="belongs to a different Session"):
        a.image_math(other=foreign)
    with pytest.raises(ValueError, match="belongs to a different Session"):
        a.mip(others=[b, foreign])  # variadic path checks every element

    assert session.images == images_before
    assert len(session.provenance.steps) == steps_before


def test_every_recorded_parent_resolves_in_its_own_session() -> None:
    """The invariant the cross-session check exists to protect."""
    session, a, b = _session_with_images()
    a.image_math(other=b, op="subtract")
    a.mip(others=[b])
    for step in session.provenance.steps:
        for image_id in step.inputs:
            assert image_id in session.images, f"{step.op} records unresolvable {image_id}"


# ── recipe inputs reach every scripting surface ───────────────────────


def test_python_pipeline_binds_a_named_input() -> None:
    session, a, b = _session_with_images()
    results = a.pipeline(
        [{"op": "image_math", "params": {"op": "subtract"}, "inputs": {"other": "dark"}}],
        inputs={"dark": b},
    )
    np.testing.assert_allclose(
        results[-1].image.to_numpy(),
        image_math(a.datastruct.data, b.datastruct.data, "subtract"),
    )
    step = session.provenance.steps[-1]
    assert step.inputs == (a.id, b.id)  # the pool member is a recorded parent


def test_pipeline_rejects_an_unbound_reference_before_running() -> None:
    session, a, b = _session_with_images()
    images_before = dict(session.images)
    with pytest.raises(ValueError, match="does not supply"):
        a.pipeline(
            [{"op": "image_math", "inputs": {"other": "dark"}}], inputs={"flat": b}
        )
    assert session.images == images_before  # nothing ran


def test_session_adopt_brings_a_struct_in_without_reparsing() -> None:
    import fermiviewer.api as fv

    session = fv.Session()
    img = session.adopt(_image(), "dark.dm4")
    assert session.images[img.id] is img
    assert img.name == "dark.dm4"
