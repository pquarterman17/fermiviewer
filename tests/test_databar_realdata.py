"""Vendor databar handling against REAL Thermo Fisher Helios TIFFs.

The synthetic fixture in test_tiff_metadata.py is self-consistent by
construction: our own writer puts `DatabarHeight` and `ResolutionY` in the
tag, so a test built on it can only prove we read back what we wrote. These
five files come off actual Helios columns (via the rosettasciio suite; see
../test-data/fei/MANIFEST.md), which is what makes the geometry assertion
below worth anything — on real files `image_rows + databar_height` really
does equal the array height, so the two independent precedence paths in
`databar_content_rows` provably agree.

They also cover the awkward variants a hand-written fixture wouldn't think
to produce: a navcam frame with no `[Scan]` block at all, one with `[IRBeam]`
stripped so nothing states a scale, and one with `HV = 'notafloat'`. The
databar geometry has to survive all three, because it is read from a
different section than the calibration that fails.

Auto-skips when the sibling corpus is absent (CI), like the other realdata
tests.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.io.metadata import databar_content_rows
from fermiviewer.io.registry import load_auto
from fermiviewer.models import ImageMeta
from fermiviewer.server import create_app
from fermiviewer.session import store

pytestmark = [pytest.mark.parser, pytest.mark.api, pytest.mark.realdata]

_DIR = "fei/microscopy"

# (filename, array shape, dtype, databar rows, scanned rows) — every value
# read off the file itself, cross-checked against the corpus MANIFEST.
CASES = [
    ("rosettasciio_Helios-Ebeam-16bits.tif", (471, 512), "uint16", 29, 442),
    ("rosettasciio_Helios-Ebeam-8bits.tif", (471, 512), "uint8", 29, 442),
    ("rosettasciio_Helios-navcam.tif", (551, 768), "uint8", 39, 512),
    ("rosettasciio_Helios-navcam-no-IRBeam.tif", (551, 768), "uint8", 39, 512),
    (
        "rosettasciio_Helios-navcam-no-IRBeam-bad-floats.tif",
        (551, 768),
        "uint8",
        39,
        512,
    ),
]
_IDS = [c[0].replace("rosettasciio_Helios-", "").removesuffix(".tif") for c in CASES]


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.mark.parametrize(("name", "shape", "dtype", "bar", "rows"), CASES, ids=_IDS)
def test_real_helios_databar_geometry(
    rsciio_examples: Path, name: str, shape: tuple[int, int], dtype: str,
    bar: int, rows: int,
) -> None:
    ds = load_auto(rsciio_examples / _DIR / name)
    assert ds.data.shape == shape          # nothing is cropped at parse time
    assert str(ds.data.dtype) == dtype
    assert ds.metadata["vendor"] == "thermofisher"
    assert ds.metadata["databar_height"] == pytest.approx(bar)
    assert ds.metadata["image_rows"] == pytest.approx(rows)

    # THE point of using real files: the vendor's two numbers are mutually
    # consistent, so `image_rows` and `n_rows - databar_height` — the two
    # branches of databar_content_rows — land on the same row. A synthetic
    # file can only ever confirm our own arithmetic.
    assert rows + bar == shape[0]
    assert databar_content_rows(ds.metadata, shape[0]) == rows
    assert databar_content_rows({"databar_height": bar}, shape[0]) == rows


@pytest.mark.parametrize(("name", "shape", "dtype", "bar", "rows"), CASES, ids=_IDS)
def test_real_helios_still_has_a_databar(
    rsciio_examples: Path, name: str, shape: tuple[int, int], dtype: str,
    bar: int, rows: int,
) -> None:
    """These files exist in the corpus to exercise the databar path, so
    assert they still do — a future corpus refresh that swapped in bar-less
    exports would otherwise leave the tests passing on nothing."""
    ds = load_auto(rsciio_examples / _DIR / name)
    content = databar_content_rows(ds.metadata, ds.data.shape[0])
    assert content is not None and content < ds.data.shape[0]
    assert ImageMeta.from_datastruct("i", name, ds).content_rows == content


def test_real_helios_strip_databar_end_to_end(client, rsciio_examples: Path) -> None:
    """Open a real Helios frame through the API and strip its bar: the cut
    row, the surviving dtype, and the acquisition provenance all come from
    the file rather than from a fixture we wrote."""
    src = rsciio_examples / _DIR / "rosettasciio_Helios-Ebeam-16bits.tif"
    opened = client.post("/api/session/open", json={"paths": [str(src)]}).json()[0]
    assert opened["shape"] == [471, 512]
    assert opened["content_rows"] == 442        # 29 databar rows below

    r = client.post("/api/strip-databar", json={"image_id": opened["id"]})
    assert r.status_code == 200
    out = r.json()
    assert out["shape"] == [442, 512]
    assert out["content_rows"] is None          # no bar left to strip
    assert out["dtype"] == "uint16"             # a pure crop, not widened

    # pixels are the top 442 rows of the original, untouched
    np.testing.assert_array_equal(
        store.get(out["id"]).data,
        np.asarray(store.get(opened["id"]).data)[:442, :],
    )
    # the provenance the databar had been displaying survives the crop
    assert out["meta"]["vendor"] == "thermofisher"
    assert out["meta"]["beam_kv"] == pytest.approx(5.0)
    assert out["meta"]["working_distance_mm"] == pytest.approx(4.03466)
    assert out["meta"]["beam"] == "EBeam"
    # and it refuses to run twice
    assert client.post(
        "/api/strip-databar", json={"image_id": out["id"]}
    ).status_code == 422


def test_real_navcam_databar_survives_a_failed_calibration(
    client, rsciio_examples: Path
) -> None:
    """`-no-IRBeam` has nothing stating a scale, so it opens uncalibrated —
    but the databar lives in `[Image]`/`[PrivateFei]`, not the calibration
    sections, so stripping it must still work. The scale bar being absent is
    exactly when a burned-in vendor bar is the only scale on the figure, so
    this combination is the one users hit, not an edge case."""
    src = rsciio_examples / _DIR / "rosettasciio_Helios-navcam-no-IRBeam.tif"
    opened = client.post("/api/session/open", json={"paths": [str(src)]}).json()[0]
    assert opened["pixel_size"] is None         # honestly uncalibrated
    assert opened["content_rows"] == 512

    out = client.post(
        "/api/strip-databar", json={"image_id": opened["id"]}
    ).json()
    assert out["shape"] == [512, 768]
    assert out["pixel_size"] is None            # still uncalibrated, not faked
