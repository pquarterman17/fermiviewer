"""`/image/{id}/render` had no size parameter, so a thumbnail was a
full-resolution PNG.

`renderUrl` is one URL serving both the Stage texture and every library
tile, and `FilmCard` renders one per loaded image. A 4096x4096 survey
image encodes to a 16.8 MB PNG in about a second, so opening a dozen
`.dm4` files asked for ~200 MB of PNG and ~20 s of encoding to paint
tiles a couple of hundred pixels wide -- which is why small batches
worked and large ones looked like a hang.

The guarantees here are the ones a caller depends on: the tile is
actually smaller, the full render is untouched, and the thumbnail carries
the SAME window as the full render rather than re-stretching a
downsampled histogram.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fermiviewer.calc.render import auto_window, to_display
from fermiviewer.server import create_app

HOST = {"host": "127.0.0.1"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _gradient(h: int, w: int) -> np.ndarray:
    """A ramp with a lone bright pixel and a lone dark one, both off the
    decimation lattice, so a naive subsample would miss the extremes and
    re-window the tile differently."""
    rng = np.random.default_rng(4)
    # noise, not a clean ramp: a pure gradient compresses to almost
    # nothing, so a byte-size comparison against it would prove nothing
    # about a real micrograph.
    img = np.linspace(1000, 3000, h * w).reshape(h, w) + rng.normal(0, 200, (h, w))
    img[min(h // 2 + 1, h - 1), min(w // 2 + 1, w - 1)] = 60000.0
    img[min(h // 2 + 3, h - 1), min(w // 2 + 3, w - 1)] = 0.0
    return np.clip(img, 0, 65535).astype(np.uint16)


def _upload(client: TestClient, arr: np.ndarray, name: str = "t.tif") -> str:
    png = io.BytesIO()
    Image.fromarray(arr).save(png, format="TIFF")
    r = client.post(
        "/api/session/upload",
        files=[("files", (name, png.getvalue(), "image/tiff"))],
        headers=HOST,
    )
    assert r.status_code == 200, r.text
    return r.json()[0]["id"]


def _png(client: TestClient, img_id: str, query: str = "") -> Image.Image:
    r = client.get(f"/api/image/{img_id}/render{query}", headers=HOST)
    assert r.status_code == 200, r.text
    return Image.open(io.BytesIO(r.content))


# ── the defect ───────────────────────────────────────────────────────────


def test_max_dim_caps_the_longest_side(client: TestClient) -> None:
    img_id = _upload(client, _gradient(600, 400))  # 600 rows x 400 cols
    # PIL .size is (width, height): the 600-row side is the longest, so it
    # becomes 128 and the width follows the aspect ratio.
    assert _png(client, img_id, "?max_dim=128").size == (85, 128)


def test_the_tile_is_dramatically_smaller_than_the_full_render(
    client: TestClient,
) -> None:
    """The point of the change, stated as bytes rather than pixels: the
    tile must not merely be a smaller image, it must not COST what the
    full render costs."""
    img_id = _upload(client, _gradient(1024, 1024))
    full = client.get(f"/api/image/{img_id}/render", headers=HOST).content
    tile = client.get(
        f"/api/image/{img_id}/render?max_dim=128", headers=HOST
    ).content
    assert len(tile) * 20 < len(full), (
        f"tile {len(tile)} B vs full {len(full)} B — not enough of a saving "
        "to matter for a library of a dozen images"
    )


def test_no_max_dim_still_returns_the_full_resolution_render(
    client: TestClient,
) -> None:
    """The Stage texture and the export path pass no `max_dim` and must
    keep getting every pixel — a default that quietly downsampled would
    degrade the main viewport."""
    arr = _gradient(600, 400)
    img_id = _upload(client, arr)
    assert _png(client, img_id).size == (400, 600)


def test_the_full_render_is_byte_for_byte_what_it_was(
    client: TestClient,
) -> None:
    """Stronger than the size check: the un-parameterised response must
    be the exact PNG the old code produced, so nothing that consumes it
    (Stage, minimap, the grains CSV overlay compositor) shifts."""
    arr = _gradient(300, 200)
    img_id = _upload(client, arr)
    got = client.get(f"/api/image/{img_id}/render", headers=HOST).content
    expected = io.BytesIO()
    Image.fromarray(to_display(arr, None, None, 1.0), mode="L").save(
        expected, format="PNG"
    )
    assert got == expected.getvalue()


# ── contrast identity ────────────────────────────────────────────────────


def test_the_thumbnail_uses_the_full_rasters_window(client: TestClient) -> None:
    """The auto window is the data's min/max. Decimating first and then
    windowing would take those bounds from the SUBSAMPLE, so a tile whose
    stride skipped the bright pixel would stretch to a different white
    point and show visibly different contrast from the Stage.

    The fixture puts its extremes at odd coordinates precisely so a
    decimated copy misses them.
    """
    arr = _gradient(512, 512)
    img_id = _upload(client, arr)
    tile = np.asarray(_png(client, img_id, "?max_dim=64"), dtype=np.float64)

    lo, hi = auto_window(arr)  # type: ignore[misc]
    assert (lo, hi) == (0.0, 60000.0), "fixture must span the full window"
    # The mid-grey level is what the window fixes. Compare the tile's mean
    # against the full render's mean rather than its extremes, which
    # resampling legitimately softens.
    full = np.asarray(_png(client, img_id), dtype=np.float64)
    assert tile.mean() == pytest.approx(full.mean(), rel=0.02)


def test_a_subsample_window_would_have_been_visibly_different() -> None:
    """Guards the test above from passing vacuously: on this fixture the
    window really does move if you take it from a decimated copy, so the
    assertion is discriminating rather than a tautology."""
    arr = _gradient(512, 512)
    full = auto_window(arr)
    sub = auto_window(arr[::8, ::8])
    assert full != sub, "fixture no longer distinguishes the two windows"


# ── boundaries ───────────────────────────────────────────────────────────


def test_max_dim_never_enlarges(client: TestClient) -> None:
    """A caller asking for a 512 px tile of a 64 px image gets the 64 px
    image, so it can ask for one size without first finding out which is
    smaller."""
    img_id = _upload(client, _gradient(64, 48))
    assert _png(client, img_id, "?max_dim=512").size == (48, 64)


@pytest.mark.parametrize("bad", ["0", "-5", "40000"])
def test_unusable_max_dim_is_rejected(client: TestClient, bad: str) -> None:
    """Zero or negative is not a size, and an absurd one would ask the
    server to enlarge into a huge PNG. 422 rather than a silent fallback,
    so a client bug surfaces instead of quietly costing what this change
    exists to avoid."""
    img_id = _upload(client, _gradient(64, 48))
    r = client.get(f"/api/image/{img_id}/render?max_dim={bad}", headers=HOST)
    assert r.status_code == 422


def test_non_square_images_keep_their_aspect_ratio(client: TestClient) -> None:
    img_id = _upload(client, _gradient(100, 400))
    w, h = _png(client, img_id, "?max_dim=100").size
    assert (w, h) == (100, 25)


def test_tiny_and_degenerate_images_survive_decimation(
    client: TestClient,
) -> None:
    """A 1-px side must not round to zero."""
    img_id = _upload(client, _gradient(1, 300))
    assert _png(client, img_id, "?max_dim=8").size == (8, 1)


def test_window_params_still_compose_with_max_dim(client: TestClient) -> None:
    """`lo`/`hi`/`gamma` are independent of the size cap; an explicit
    window must survive being asked for as a tile."""
    arr = _gradient(256, 256)
    img_id = _upload(client, arr)
    dark = np.asarray(_png(client, img_id, "?max_dim=32&lo=0&hi=60000"))
    bright = np.asarray(_png(client, img_id, "?max_dim=32&lo=0&hi=3000"))
    assert bright.mean() > dark.mean()
