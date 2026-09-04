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
import tracemalloc

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fermiviewer.calc.render import auto_window, to_display
from fermiviewer.calc.thumbnail import _box_reduce, decimate, display_png
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


# ── aliasing: periodic structure is the subject, not a corner case ───────


def _checkerboard(n: int, roll_rows: int = 0, roll_cols: int = 0) -> np.ndarray:
    """Alternating full-scale pixels — the worst case for subsampling,
    and the phase shift is what makes the failure unmistakable."""
    x = (np.indices((n, n)).sum(axis=0) % 2 * 65535).astype(np.uint16)
    return np.roll(np.roll(x, roll_rows, axis=0), roll_cols, axis=1)


@pytest.mark.parametrize(("roll_rows", "roll_cols"), [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_a_checkerboard_reduces_to_mid_grey_at_every_phase(
    roll_rows: int, roll_cols: int
) -> None:
    """The regression this section exists for.

    Point subsampling with an even stride lands on ONE phase of a
    checkerboard, so the tile came out entirely black — and entirely
    white for the same image shifted a single row, where the honest
    answer is a uniform mid-grey. No later resampling pass can undo that:
    the intensities are already gone by the time it runs.

    Asserting the phases agree is not enough on its own (all-black and
    all-black would agree), so the mid-grey VALUE is pinned too.
    """
    png = display_png(_checkerboard(512, roll_rows, roll_cols), max_edge=64)
    tile = np.asarray(Image.open(io.BytesIO(png)), dtype=np.float64)
    assert tile.mean() == pytest.approx(128.0, abs=2.0)
    # np.ptp, not ndarray.ptp -- the method was removed in numpy 2
    assert np.ptp(tile) <= 2, "a uniform pattern must not develop false structure"


@pytest.mark.parametrize("phase", [0, 1, 2, 3])
def test_stripes_keep_their_contrast_whatever_the_phase(phase: int) -> None:
    """Lattice fringes are the realistic form of this: a period-8 stripe
    field must average to grey rather than resolving to whichever phase
    the sampling lattice happened to land on."""
    cols = np.indices((1024, 1024))[1]
    stripes = (((cols + phase) // 4 % 2) * 65535).astype(np.uint16)
    png = display_png(stripes, max_edge=64)
    tile = np.asarray(Image.open(io.BytesIO(png)), dtype=np.float64)
    assert tile.mean() == pytest.approx(128.0, abs=2.0)


def test_the_library_target_size_is_covered_too() -> None:
    """The unit tests above use a small `max_edge`; the size the UI
    actually asks for is 512 from a 4096 px survey image, where the
    reduction factor is different. Guard the real path, not only a
    convenient one."""
    for roll in (0, 1):
        png = display_png(_checkerboard(2048, roll_rows=roll), max_edge=512)
        tile = np.asarray(Image.open(io.BytesIO(png)), dtype=np.float64)
        assert tile.mean() == pytest.approx(128.0, abs=2.0)


def test_the_reduction_stays_within_its_memory_budget() -> None:
    """The reduction exists to avoid `window_level`'s full-size float64
    temporaries, so it must not allocate one itself. A 4096x4096 uint16
    raster is 33.6 MB and its float64 cast would be 134 MB."""
    rng = np.random.default_rng(0)
    big = rng.integers(0, 4000, (4096, 4096), dtype=np.uint16)
    tracemalloc.start()
    display_png(big, max_edge=512)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 60e6, f"peak allocation {peak / 1e6:.0f} MB is not bounded"


# ── the complete source extent, including partial edge blocks ────────────


@pytest.mark.parametrize("n", [513, 1000, 999])
def test_a_bright_final_row_survives_an_odd_sized_image(n: int) -> None:
    """Flooring the output dimensions and slicing to the last whole block
    deletes up to k-1 source rows and columns.

    On a 513x513 image with k = 8 that dropped row 512 outright, so an
    image whose ONLY content is a bright final row rendered entirely
    black. The final resize cannot recover it — the samples were never
    read.
    """
    arr = np.zeros((n, n), dtype=np.uint16)
    arr[-1, :] = 65535
    tile = np.asarray(
        Image.open(io.BytesIO(display_png(arr, max_edge=64))), dtype=np.float64
    )
    assert tile.max() > 0, "the bright final row was cropped away"


def test_a_bright_final_column_survives_too() -> None:
    """The same for the other axis — flooring `wb` crops columns exactly
    as flooring `hb` crops rows, and a fixture that only moves rows would
    not notice."""
    arr = np.zeros((513, 513), dtype=np.uint16)
    arr[:, -1] = 65535
    tile = np.asarray(
        Image.open(io.BytesIO(display_png(arr, max_edge=64))), dtype=np.float64
    )
    assert tile.max() > 0, "the bright final column was cropped away"


def test_a_thin_image_keeps_all_of_its_rows() -> None:
    """A 3 x 1024 strip at the real `max_edge` of 512 gives k = 2. Cropping
    to whole blocks returned a single row and discarded a THIRD of the
    source; ceil keeps both."""
    arr = np.zeros((3, 1024), dtype=np.uint16)
    arr[-1, :] = 65535
    img = Image.open(io.BytesIO(display_png(arr, max_edge=512)))
    assert img.size == (512, 2), f"{img.size} — a third of the source is missing"
    assert np.asarray(img).max() > 0


@pytest.mark.parametrize(
    ("h", "w", "k"), [(513, 513, 8), (1000, 999, 7), (37, 91, 11), (3, 1024, 2)]
)
def test_the_reduction_conserves_the_total_exactly(h: int, w: int, k: int) -> None:
    """The precise form of 'nothing was thrown away'.

    Each output value is the mean of its block, so multiplying it back by
    that block's true sample count and summing must reproduce the input
    sum EXACTLY. Cropping partial blocks loses their contribution and this
    fails by the size of the discarded strip.

    Asserted on `_box_reduce` rather than through the PNG, because
    windowing to 8 bits and the final resample both move values for
    legitimate reasons and would blunt the check.
    """
    rng = np.random.default_rng(3)
    arr = rng.integers(0, 65535, (h, w), dtype=np.uint16)
    out = _box_reduce(arr, k)

    row_counts = np.diff(np.append(np.arange(0, h, k), h))
    col_counts = np.diff(np.append(np.arange(0, w, k), w))
    assert out.shape == (row_counts.size, col_counts.size)
    weights = row_counts[:, None] * col_counts[None, :]
    assert (out * weights).sum() == pytest.approx(
        float(arr.sum()), rel=1e-12
    ), "the reduction dropped or double-counted source pixels"


def test_the_tile_mean_tracks_the_full_render() -> None:
    """The same claim end to end, at sizes where it is meaningful.

    Only approximate, and not from sloppiness: a short edge block is the
    honest mean of the few samples it covers, but it still occupies a
    whole output pixel, so it carries more weight in the tile than its
    area does in the source. That gap grows as the output shrinks and the
    remainder grows — on a 4x9 tile it reaches ~1.5 grey levels. The exact
    conservation law is the test above; this one guards the wiring.
    """
    rng = np.random.default_rng(3)
    for h, w, edge in ((513, 513, 64), (1000, 999, 128), (4096, 4096, 512)):
        arr = rng.integers(0, 65535, (h, w), dtype=np.uint16)
        tile = np.asarray(
            Image.open(io.BytesIO(display_png(arr, max_edge=edge))), dtype=np.float64
        )
        full = np.asarray(
            Image.open(io.BytesIO(display_png(arr))), dtype=np.float64
        )
        assert tile.mean() == pytest.approx(full.mean(), abs=0.5)


# ── output size comes from the SOURCE, not the intermediate ──────────────


def _source_derived_size(h: int, w: int, edge: int) -> tuple[int, int]:
    """PIL ``(width, height)`` a full-image resize would produce.

    Deliberately written from the original extent alone, with no reference
    to the reduction — that independence is the whole point.
    """
    longest = max(h, w)
    if longest <= edge:
        return (w, h)
    s = edge / longest
    return (max(1, round(w * s)), max(1, round(h * s)))


@pytest.mark.parametrize(
    ("h", "w", "edge"),
    [
        (9, 4096, 512),     # ceil gives 2 rows; the source implies 1.1 -> 1
        (4096, 9, 512),     # transposed, wrong in the same way
        (7, 4096, 512),
        (3, 1024, 512),
        (1024, 3, 512),
        (513, 513, 64),
        (600, 400, 128),
        (100, 400, 100),
        (1, 300, 8),
        (64, 48, 512),      # already smaller than the cap
    ],
)
def test_the_tile_has_the_size_a_full_image_resize_would_give(
    h: int, w: int, edge: int
) -> None:
    """`_box_reduce` rounds each axis UP, so a very oblong source lands
    thicker than its aspect ratio allows.

    Sizing from that intermediate left a 9x4096 raster at `max_edge=512`
    as a 512x2 tile, doubling the image's thickness, because its longest
    edge was already 512 and nothing asked what the SOURCE implied
    (9/4096 * 512 = 1.1 rows).
    """
    got = Image.open(
        io.BytesIO(display_png(np.zeros((h, w), dtype=np.uint16), max_edge=edge))
    ).size
    assert got == _source_derived_size(h, w, edge)


def test_the_size_fixtures_actually_discriminate() -> None:
    """Guards the test above from passing for the wrong reason.

    A ceil-sized reduction and the source-derived rounding agree on many
    shapes — 3x1024 gives 2 rows either way, which is why the earlier thin
    -image test could not catch this. At least one fixture must disagree,
    or the assertion above is satisfied by the very code it rejects.
    """
    disagreeing = [
        (h, w, e)
        for h, w, e in ((9, 4096, 512), (4096, 9, 512), (3, 1024, 512))
        if _ceil_reduced_size(h, w, e) != _source_derived_size(h, w, e)
    ]
    assert disagreeing, "no fixture distinguishes ceil sizing from source sizing"
    assert (3, 1024, 512) not in disagreeing, (
        "3x1024 is expected to agree — it is the case that used to hide this"
    )


def _ceil_reduced_size(h: int, w: int, edge: int) -> tuple[int, int]:
    """What sizing from the reduced intermediate alone would have given."""
    k = min(max(h, w) // edge, h, w)
    if k < 2:
        return (w, h)
    rh, rw = -(-h // k), -(-w // k)
    longest = max(rh, rw)
    if longest <= edge:
        return (rw, rh)
    s = edge / longest
    return (max(1, round(rw * s)), max(1, round(rh * s)))


def test_the_final_resize_never_enlarges() -> None:
    """Sizing from the source is only safe because the reduction always
    lands at or above that target: `_box_reduce` divides by an integer
    ``k <= longest / max_edge``. If it could land BELOW, resizing up would
    invent resolution."""
    for h, w, edge in ((9, 4096, 512), (4096, 9, 512), (513, 513, 64), (37, 91, 8)):
        tw, th = _source_derived_size(h, w, edge)
        reduced = decimate(np.zeros((h, w), dtype=np.uint16), edge)
        assert reduced.shape[0] >= th and reduced.shape[1] >= tw, (
            f"{h}x{w}@{edge}: reduced {reduced.shape} is smaller than target "
            f"{(th, tw)} — the resize would be an upscale"
        )


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
