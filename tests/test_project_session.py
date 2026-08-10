"""The open project's session state (plan #34/#35) — placeholder ownership
and the resolution order a re-point appends to.

Server-side, not client-side: this is what makes the no-data-loss guarantee
independent of the client. The route tests in test_api_project_io.py exercise
the same code through HTTP; these pin the two decisions that are easy to get
subtly wrong.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import tifffile

from fermiviewer.datastruct import AxisCal, DataKind
from fermiviewer.io.project_manifest import LoadedProject, ProjectImage
from fermiviewer.project_session import ProjectSession

AXES = (AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm"))


def _placeholder(img_id: str = "img1", rel: str = "frame.tif") -> ProjectImage:
    return ProjectImage(
        id=img_id,
        name=Path(rel).name,
        kind=DataKind.IMAGE,
        axes=AXES,
        rel=rel,
        data=None,
        unavailable=True,
    )


def _loaded(*images: ProjectImage, hint: str | None = None) -> LoadedProject:
    return LoadedProject(images=images, data_root_hint=hint)


def _source(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(path, np.full((3, 4), 7, dtype=np.uint16))


def test_only_unresolved_images_are_kept(tmp_path: Path) -> None:
    """Resolved images live in the session store; keeping a second copy here
    would let the two disagree about what is open."""
    resolved = ProjectImage(
        id="ok", name="ok.tif", kind=DataKind.IMAGE, axes=AXES,
        data=np.zeros((3, 4), dtype=np.uint16),
    )
    session = ProjectSession()
    session.adopt(_loaded(resolved, _placeholder()), tmp_path / "s.fvp")
    assert [img.id for img in session.placeholders()] == ["img1"]


def test_a_user_root_is_appended_after_the_hint_and_the_project_dir(
    tmp_path: Path,
) -> None:
    """ADR 0002 §3's order is preserved, not replaced (item 34's wording):
    the hint keeps its precedence so a remounted drive takes over again
    without the user having to undo a re-point."""
    hint = tmp_path / "hint"
    picked = tmp_path / "picked"
    for d in (hint, picked):
        d.mkdir()
    _source(picked / "frame.tif")

    session = ProjectSession()
    session.adopt(_loaded(_placeholder(), hint=str(hint)), tmp_path / "proj" / "s.fvp")
    assert session.search_order() == (hint, tmp_path / "proj")
    assert session.search_order(picked) == (hint, tmp_path / "proj", picked)

    session.relocate(picked)
    # remembered for later saves and loads, still last in the order
    assert session.current().extra_roots == (str(picked),)
    assert session.search_order() == (hint, tmp_path / "proj", picked)


def test_a_root_that_resolved_nothing_is_not_remembered(tmp_path: Path) -> None:
    """An accumulating list of wrong guesses would slow every later
    resolution down for nothing."""
    empty = tmp_path / "empty"
    empty.mkdir()
    session = ProjectSession()
    session.adopt(_loaded(_placeholder()), tmp_path / "s.fvp")

    outcome = session.relocate(empty)
    assert outcome.resolved == ()
    assert [img.id for img in outcome.still_unavailable] == ["img1"]
    assert session.current().extra_roots == ()
    assert [img.id for img in session.placeholders()] == ["img1"]  # still pending


def test_a_resolved_placeholder_stops_being_pending(tmp_path: Path) -> None:
    picked = tmp_path / "picked"
    picked.mkdir()
    _source(picked / "frame.tif")
    session = ProjectSession()
    session.adopt(_loaded(_placeholder(), _placeholder("img2", "gone.tif")), tmp_path)

    outcome = session.relocate(picked)
    assert [img.id for img in outcome.resolved] == ["img1"]
    assert outcome.resolved[0].data is not None
    assert outcome.resolved[0].unavailable is False
    assert [img.id for img in session.placeholders()] == ["img2"]


def test_note_save_moves_the_project_dir_used_for_resolution(tmp_path: Path) -> None:
    """Saving beside the data makes those images resolve on the next open with
    no re-point at all — the project's own directory is a search root."""
    beside = tmp_path / "beside"
    beside.mkdir()
    session = ProjectSession()
    session.adopt(_loaded(_placeholder()), tmp_path / "elsewhere" / "s.fvp")
    assert session.search_order() == (tmp_path / "elsewhere",)

    session.note_save(beside / "s.fvp", "light", "Study")
    assert session.search_order() == (beside,)
    assert session.current().name == "Study"
    assert session.current().payload_mode == "light"


def test_an_append_load_keeps_the_open_project_s_placeholders(tmp_path: Path) -> None:
    """`/project/load` with `replace: false` merges a second project into the
    session. Overwriting the placeholder list there would drop the FIRST
    project's unresolved references, and its next save would write that loss to
    disk — the one thing ADR 0002 §4 forbids."""
    session = ProjectSession()
    session.adopt(
        _loaded(_placeholder("first", "s1/a.tif"), hint="/data/one"),
        tmp_path / "one" / "one.fvp",
    )
    session.adopt(
        _loaded(_placeholder("second", "s2/b.tif"), hint="/data/two"),
        tmp_path / "two" / "two.fvp",
        merge=True,
    )

    state = session.current()
    assert [img.id for img in state.placeholders] == ["first", "second"]
    # the session still belongs to the project that was already open
    assert state.path == str(tmp_path / "one" / "one.fvp")
    assert state.data_root_hint == "/data/one"
    # ...and the merged project's roots are searchable, so its references are
    # not resolvable by hand only
    assert session.search_order()[-2:] == (Path("/data/two"), tmp_path / "two")


def test_merging_the_same_project_twice_does_not_double_it(tmp_path: Path) -> None:
    session = ProjectSession()
    loaded = _loaded(_placeholder())
    session.adopt(loaded, tmp_path / "s.fvp")
    session.adopt(loaded, tmp_path / "s.fvp", merge=True)
    assert [img.id for img in session.placeholders()] == ["img1"]


def test_an_append_load_with_nothing_open_adopts_normally(tmp_path: Path) -> None:
    session = ProjectSession()
    session.adopt(_loaded(_placeholder(), hint="/data"), tmp_path / "s.fvp", merge=True)
    assert session.current().data_root_hint == "/data"
    assert session.current().path == str(tmp_path / "s.fvp")


def test_a_replacing_load_forgets_the_previous_project(tmp_path: Path) -> None:
    session = ProjectSession()
    session.adopt(_loaded(_placeholder("first")), tmp_path / "one.fvp")
    session.adopt(_loaded(_placeholder("second")), tmp_path / "two.fvp")
    assert [img.id for img in session.placeholders()] == ["second"]


def test_clear_forgets_everything(tmp_path: Path) -> None:
    session = ProjectSession()
    session.adopt(_loaded(_placeholder(), hint="/data"), tmp_path / "s.fvp")
    session.clear()
    assert session.placeholders() == ()
    assert session.current().data_root_hint is None
    assert session.current().path is None
