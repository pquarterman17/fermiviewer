"""User-configurable metadata: YAML schema, filename {field} templates,
sidecar persistence, and the API surface."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer import usermeta
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.api

CONFIG = """\
fields:
  - Design
  - Lot
  - Wafer
  - Reticle
pattern: "D{Design}_L{Lot}_W{Wafer}_R{Reticle}"
"""


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "metadata.yaml"
    p.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("FV_METADATA_CONFIG", str(p))
    return p


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open(client, tmp_path, name: str) -> str:
    f = write_mini_dm4(
        tmp_path / name, dims=[8, 8], data=np.zeros(64),
        cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


# ── unit: filename templates ──────────────────────────────────────────


def test_parse_filename_template() -> None:
    vals = usermeta.parse_filename(
        "D1234_L44576_W1234_R13.dm4",
        ("D{Design}_L{Lot}_W{Wafer}_R{Reticle}",),
    )
    assert vals == {
        "Design": "1234", "Lot": "44576", "Wafer": "1234", "Reticle": "13",
    }


def test_parse_filename_no_match() -> None:
    assert usermeta.parse_filename("random.dm4", ("D{Design}_L{Lot}",)) == {}


def test_parse_filename_first_match_wins() -> None:
    pats = ("{Lot}-{Wafer}", "D{Design}_L{Lot}_W{Wafer}_R{Reticle}")
    assert usermeta.parse_filename("D1_L2_W3_R4.dm4", pats) == {
        "Design": "1", "Lot": "2", "Wafer": "3", "Reticle": "4",
    }


# ── unit: sidecar + schema + resolution ───────────────────────────────


def test_sidecar_round_trip(tmp_path) -> None:
    img = tmp_path / "x.dm4"
    img.write_bytes(b"")
    usermeta.write_sidecar(str(img), {"Design": "9", "Lot": "abc"})
    assert usermeta.sidecar_path(str(img)).name == "x.dm4.fvmeta.yaml"
    assert usermeta.read_sidecar(str(img)) == {"Design": "9", "Lot": "abc"}


def test_load_schema_from_config(cfg) -> None:
    s = usermeta.load_schema()
    assert [f.name for f in s.fields] == ["Design", "Lot", "Wafer", "Reticle"]
    assert s.patterns == ("D{Design}_L{Lot}_W{Wafer}_R{Reticle}",)


def test_load_schema_typed_fields(tmp_path, monkeypatch) -> None:
    p = tmp_path / "metadata.yaml"
    p.write_text(
        "fields:\n"
        "  - Design\n"
        "  - {name: Wafer, type: number}\n"
        "  - {name: Process, options: [A, B, C]}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FV_METADATA_CONFIG", str(p))
    s = usermeta.load_schema()
    assert s.fields[0] == usermeta.MetaField(name="Design")
    assert s.fields[1] == usermeta.MetaField(name="Wafer", type="number")
    assert s.fields[2] == usermeta.MetaField(
        name="Process", options=("A", "B", "C")
    )


def test_load_schema_seeds_starter(tmp_path, monkeypatch) -> None:
    p = tmp_path / "sub" / "metadata.yaml"
    monkeypatch.setenv("FV_METADATA_CONFIG", str(p))
    s = usermeta.load_schema()
    assert p.exists()  # commented starter written on first read
    assert len(s.fields) >= 1


def test_resolve_precedence(cfg, tmp_path) -> None:
    img = tmp_path / "D1_L2_W3_R4.dm4"
    img.write_bytes(b"")
    usermeta.write_sidecar(str(img), {"Lot": "saved"})
    schema = usermeta.load_schema()
    vals = usermeta.resolve_values(schema, img.name, str(img), {"Wafer": "live"})
    assert vals["Design"] == "1"      # from filename
    assert vals["Lot"] == "saved"     # sidecar overrides filename
    assert vals["Wafer"] == "live"    # session edit overrides both


# ── API ───────────────────────────────────────────────────────────────


def test_schema_endpoint(cfg, client) -> None:
    r = client.get("/api/metadata-schema").json()
    assert [f["name"] for f in r["fields"]] == ["Design", "Lot", "Wafer", "Reticle"]
    assert r["config_path"].endswith("metadata.yaml")


def test_usermeta_autofill_and_save(cfg, client, tmp_path) -> None:
    img_id = _open(client, tmp_path, "D1234_L44576_W1234_R13.dm4")
    got = client.get(f"/api/image/{img_id}/usermeta").json()
    assert got["values"]["Design"] == "1234"  # auto-filled from the name
    assert got["can_write_sidecar"] is True
    assert got["has_sidecar"] is False

    saved = client.post(
        f"/api/image/{img_id}/usermeta",
        json={"values": {"Design": "1234", "Lot": "X"}},
    ).json()
    assert saved["wrote_sidecar"] is True
    assert (tmp_path / "D1234_L44576_W1234_R13.dm4.fvmeta.yaml").exists()

    again = client.get(f"/api/image/{img_id}/usermeta").json()
    assert again["values"]["Lot"] == "X"   # saved value wins over filename
    assert again["has_sidecar"] is True


def test_usermeta_unknown_id(cfg, client) -> None:
    assert client.get("/api/image/nope/usermeta").status_code == 404


def test_patterns_as_bare_string(tmp_path, monkeypatch) -> None:
    # `patterns:` given a string (not a list) must not iterate char-by-char
    p = tmp_path / "metadata.yaml"
    p.write_text(
        'fields: [Design, Lot]\npatterns: "D{Design}_L{Lot}"\n', encoding="utf-8"
    )
    monkeypatch.setenv("FV_METADATA_CONFIG", str(p))
    s = usermeta.load_schema()
    assert s.patterns == ("D{Design}_L{Lot}",)
    assert usermeta.parse_filename("D1_L2.dm4", s.patterns) == {
        "Design": "1", "Lot": "2",
    }


def test_duplicate_fields_deduped(tmp_path, monkeypatch) -> None:
    p = tmp_path / "metadata.yaml"
    p.write_text("fields: [Design, Design, Lot]\n", encoding="utf-8")
    monkeypatch.setenv("FV_METADATA_CONFIG", str(p))
    assert [f.name for f in usermeta.load_schema().fields] == ["Design", "Lot"]


def test_sidecar_null_is_empty(tmp_path) -> None:
    img = tmp_path / "x.dm4"
    img.write_bytes(b"")
    (tmp_path / "x.dm4.fvmeta.yaml").write_text("Lot: null\n", encoding="utf-8")
    assert usermeta.read_sidecar(str(img)) == {"Lot": ""}


def test_resolve_session_can_clear(cfg) -> None:
    # no source_path (upload/derived); an explicit empty session value clears
    schema = usermeta.load_schema()
    vals = usermeta.resolve_values(schema, "D1_L2_W3_R4.dm4", None, {"Lot": ""})
    assert vals["Lot"] == ""   # explicit clear wins over filename "2"
    assert vals["Design"] == "1"


def test_resolve_session_keeps_zero(cfg) -> None:
    # 0 / False must not be treated as "unset"
    schema = usermeta.load_schema()
    vals = usermeta.resolve_values(schema, "D1_L2_W3_R4.dm4", None, {"Wafer": 0})
    assert vals["Wafer"] == "0"


def test_batch_preserves_sidecar_correction(cfg, client, tmp_path) -> None:
    img_id = _open(client, tmp_path, "D1234_L44576_W1234_R13.dm4")
    # user fixed a typo in the sidecar
    usermeta.write_sidecar(
        str(tmp_path / "D1234_L44576_W1234_R13.dm4"), {"Lot": "44577"}
    )
    client.post("/api/usermeta/batch-autofill", json={"image_ids": [img_id]})
    got = client.get(f"/api/image/{img_id}/usermeta").json()
    assert got["values"]["Lot"] == "44577"   # NOT clobbered by filename 44576
    assert got["values"]["Design"] == "1234"  # filename still fills the rest


def test_batch_autofill(cfg, client, tmp_path) -> None:
    match_id = _open(client, tmp_path, "D1234_L44576_W1234_R13.dm4")
    nomatch_id = _open(client, tmp_path, "random.dm4")
    r = client.post(
        "/api/usermeta/batch-autofill",
        json={"image_ids": [match_id, nomatch_id, "ghost"]},
    ).json()
    assert r["n_total"] == 2  # "ghost" id skipped
    assert r["n_matched"] == 1
    # the matching file got a sidecar written from its name
    assert (tmp_path / "D1234_L44576_W1234_R13.dm4.fvmeta.yaml").exists()
    # and its values are now resolvable
    got = client.get(f"/api/image/{match_id}/usermeta").json()
    assert got["values"]["Wafer"] == "1234"
    assert got["has_sidecar"] is True
