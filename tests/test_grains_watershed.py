"""Modern grain segmentation (watershed / RAG / orientation) + the
upgraded boundary metrics. These carry NO MATLAB-parity obligation, so
they validate against deterministic synthetic fixtures rather than goldens.
The ported k-means path keeps its golden in test_atoms_grains.py.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from skimage.filters import gaussian

from fermiviewer.calc.grain_size import astm_grain_size_number
from fermiviewer.calc.grains import (
    _normalize01,
    _robust_normalize01,
    _sanitize,
    enforce_connected_grains,
    grain_stats,
    segment_watershed,
    split_grain,
)
from fermiviewer.calc.segment import label_components

pytestmark = pytest.mark.imaging


@pytest.fixture
def striped() -> np.ndarray:
    """Whole-field tiling: three vertical bands of distinct intensity with
    soft boundaries — a clean 3-grain target for gradient & RAG modes."""
    img = np.zeros((60, 90), dtype=np.float64)
    img[:, :30] = 0.2
    img[:, 30:60] = 0.6
    img[:, 60:] = 1.0
    return gaussian(img, sigma=1.0)


def test_gradient_watershed_recovers_bands(striped) -> None:
    seg = segment_watershed(striped, method="gradient", granularity=0.05, min_area=50)
    assert seg.method == "gradient"
    assert seg.n_grains == 3


def test_rag_recovers_bands() -> None:
    # sharp intensity steps (what diffraction-contrast grains look like) so
    # superpixels don't chain-merge across a soft transition
    img = np.zeros((60, 90), dtype=np.float64)
    img[:, :30] = 0.2
    img[:, 30:60] = 0.6
    img[:, 60:] = 1.0
    seg = segment_watershed(
        img, method="rag", n_superpixels=200, merge_threshold=0.2, min_area=50
    )
    assert seg.n_grains == 3


def test_orientation_splits_two_lattices() -> None:
    yy, xx = np.mgrid[0:80, 0:80]
    left = np.sin(xx * 0.8)   # vertical fringes
    right = np.sin(yy * 0.8)  # horizontal fringes
    img = np.where(xx < 40, left, right).astype(np.float64)
    seg = segment_watershed(
        img, method="orientation", granularity=0.04,
        orientation_sigma=2.0, min_area=100,
    )
    assert seg.n_grains == 2


# ── robustness: outlier rejection, NaN safety, denoise ───────────────

def test_sanitize_replaces_nonfinite() -> None:
    a = np.array([[1.0, np.nan], [np.inf, 3.0]])
    s = _sanitize(a)
    assert np.all(np.isfinite(s))
    assert s[0, 0] == 1.0 and s[1, 1] == 3.0
    assert s[0, 1] == 2.0 and s[1, 0] == 2.0     # median of finite {1, 3}


def test_sanitize_is_noop_on_clean_data() -> None:
    a = np.linspace(0.0, 1.0, 12).reshape(3, 4)
    np.testing.assert_array_equal(_sanitize(a), a)


def test_robust_normalize_clips_hot_pixel() -> None:
    a = np.linspace(0.0, 1.0, 2500).reshape(50, 50)
    a[0, 0] = 1e6                                  # detector spike
    n = _robust_normalize01(a)                     # default 0.5% clip
    assert 0.0 <= float(n.min()) and float(n.max()) <= 1.0
    assert n[-1, -1] > 0.9                         # real max still maps near 1
    assert _normalize01(a)[-1, -1] < 0.01          # min/max stretch crushes it


def test_rag_watershed_survives_hot_pixel() -> None:
    # rag merges on absolute mean intensity, so a single saturated pixel that
    # crushes the [0,1] stretch makes every band look equal → all merge.
    img = np.zeros((60, 90), dtype=np.float64)
    img[:, :30] = 0.2
    img[:, 30:60] = 0.6
    img[:, 60:] = 1.0
    img[10, 10] = 1e6                              # single detector spike
    robust = segment_watershed(
        img, method="rag", n_superpixels=200, merge_threshold=0.2, min_area=50
    )
    naive = segment_watershed(
        img, method="rag", n_superpixels=200, merge_threshold=0.2,
        min_area=50, robust=False,
    )
    assert robust.n_grains == 3                    # outlier clipped → bands recovered
    assert naive.n_grains < 3                      # crushed contrast merges the bands


def test_gradient_watershed_survives_nan_region(striped) -> None:
    img = striped.copy()
    img[0:3, 0:3] = np.nan                         # masked corner
    seg = segment_watershed(img, method="gradient", granularity=0.05, min_area=50)
    assert seg.n_grains == 3                        # NaNs filled, bands still found


def test_denoise_reduces_noise_oversegmentation() -> None:
    rng = np.random.default_rng(0)
    img = np.zeros((80, 120), dtype=np.float64)
    img[:, :60] = 0.3
    img[:, 60:] = 0.7
    noisy = img + rng.normal(0.0, 0.15, img.shape)
    raw = segment_watershed(noisy, method="gradient", granularity=0.05, min_area=30)
    smoothed = segment_watershed(
        noisy, method="gradient", granularity=0.05, min_area=30, denoise_sigma=2.0
    )
    assert raw.n_grains > smoothed.n_grains         # denoise merges noise fragments
    assert smoothed.n_grains >= 2                    # the two real grains survive


def test_unknown_method_raises(striped) -> None:
    with pytest.raises(ValueError):
        segment_watershed(striped, method="nonsense")


def test_crofton_perimeter_of_a_disk() -> None:
    yy, xx = np.mgrid[0:100, 0:100]
    r = 20.0
    disk = ((xx - 50) ** 2 + (yy - 50) ** 2) <= r**2
    labels = disk.astype(np.int64)
    gs = grain_stats(labels, disk.astype(np.float64), pixel_size=1.0)
    # true perimeter 2πr ≈ 125.7; Crofton estimate within a few percent —
    # and FAR from the naive boundary-pixel count this replaces
    assert gs.perimeter_crofton_px[0] == pytest.approx(2 * math.pi * r, rel=0.05)


def test_triple_junction_count() -> None:
    labels = np.zeros((80, 80), dtype=np.int64)
    labels[:40, :40] = 1
    labels[:40, 40:] = 2
    labels[40:, :40] = 3
    labels[40:, 40:] = 4
    gs = grain_stats(labels, labels.astype(np.float64))
    assert gs.n_triple_junctions == 1
    assert gs.n_grains == 4


def test_boundary_network_length() -> None:
    # three equal strips tiling a 10×30 field → 2 internal boundaries × 10
    labels = np.zeros((10, 30), dtype=np.int64)
    labels[:, :10] = 1
    labels[:, 10:20] = 2
    labels[:, 20:] = 3
    gs = grain_stats(labels, np.zeros((10, 30)))
    assert gs.boundary_network_px == 20.0  # not the inflated perim-sum/2 (~55)
    # a single grain has no shared boundaries
    one = np.ones((10, 10), dtype=np.int64)
    assert grain_stats(one, np.zeros((10, 10))).boundary_network_px == 0.0


def test_split_grain_labels_stay_connected() -> None:
    # a field with an isolated tiny basin the old code would orphan into a
    # second, disconnected piece sharing grain_id
    img = np.ones((50, 50)) * 0.5
    img[5:20, 5:20] = 0.01
    img[25, 25] = 0.005
    img[5:20, 30:45] = 0.01
    img[30:45, 5:45] = 0.01
    img[21:24, :] = 1.0
    labels = np.zeros((50, 50), dtype=np.int64)
    labels[1:49, 1:49] = 1
    out = split_grain(labels, img, grain_id=1, granularity=1e-7)
    for v in np.unique(out):
        if v > 0:
            _, ncc = label_components(out == v, 8)
            assert ncc == 1, f"label {v} disconnected ({ncc} components)"


def test_enforce_connected_splits_disconnected_label() -> None:
    # mimics merging two non-adjacent grains into one label
    labels = np.zeros((10, 30), dtype=np.int64)
    labels[:, :10] = 1
    labels[:, 20:] = 1  # same id, spatially separate
    labels[:, 10:20] = 2
    out = enforce_connected_grains(labels)
    assert out[0, 0] != out[0, 25]  # the two pieces become distinct grains
    for v in np.unique(out):
        if v > 0:
            _, ncc = label_components(out == v, 8)
            assert ncc == 1


def test_segment_watershed_rejects_tiny_image() -> None:
    with pytest.raises(ValueError):
        segment_watershed(np.array([[0.5, 0.6, 0.7]]), method="orientation")


#: ASTM E112-13, grains per square millimetre against the grain-size
#: number, read from the standard's own table. An INDEPENDENT anchor:
#: these are published pairs, not this implementation restated.
E112_TABLE = [
    # (G, grains per mm^2)
    (1.0, 15.5),
    (3.0, 62.0),
    (5.0, 248.0),
    (8.0, 1980.0),
    (10.0, 7936.0),
]


@pytest.mark.parametrize(("g", "grains_per_mm2"), E112_TABLE)
def test_astm_grain_size_matches_the_published_table(g, grains_per_mm2) -> None:
    """Checked against ASTM E112's own G/density pairs.

    The previous test recomputed the implementation's expression and
    asserted the two agreed, which is true of ANY formula and was true
    while this one used `log2` with a coefficient built for `log10` — a
    slope 3.32x too steep that reported G = 40.8 for 10 um grains, when
    the scale itself only runs to about 14.

    The table gives grains per mm^2; the function takes an equivalent
    circular diameter, so the conversion here is the one algebraic step
    (`D = 2*sqrt(A/pi)` for `A = 1/N_A`) and nothing else is shared with
    the implementation.
    """
    area_mm2 = 1.0 / grains_per_mm2
    diameter_mm = 2.0 * math.sqrt(area_mm2 / math.pi)
    got = astm_grain_size_number(diameter_mm * 1000.0, "um")
    assert got == pytest.approx(g, abs=0.02)


def test_astm_grain_size_matches_the_closed_form_its_docstring_states() -> None:
    """`astm_grain_size_number`'s docstring carries the collapsed form
    ``G = -6.643856*log10(D_mm) - 2.6055``, which the code never
    evaluates — it composes the density relation instead. A stated
    constant nothing executes is a constant nothing checks, and the
    module's whole claim is that its constants can be checked rather
    than trusted, so check this one: the tolerance is tight enough that
    a wrong digit in the last place of the offset fails.
    """
    for diameter_um in (0.5, 5.0, 50.0, 500.0):
        d_mm = diameter_um * 1e-3
        stated = -6.643856 * math.log10(d_mm) - 2.6055
        assert astm_grain_size_number(diameter_um, "um") == pytest.approx(
            stated, abs=2e-5
        ), f"docstring's closed form disagrees at {diameter_um} um"


def test_astm_grain_size_stays_on_its_own_scale() -> None:
    """A guard against the failure that actually happened rather than
    against a formula: ASTM numbers run roughly 00 to 14 over the grain
    sizes microscopy sees, so anything far outside that means the slope
    or the log base is wrong, whatever the expression looks like."""
    for diameter_um in (0.5, 1.0, 10.0, 100.0, 500.0):
        g = astm_grain_size_number(diameter_um, "um")
        assert -4.0 < g < 20.0, f"{diameter_um} um gave G={g}"
    # and it must DECREASE as grains get bigger
    coarse = [astm_grain_size_number(d, "um") for d in (1.0, 10.0, 100.0)]
    assert coarse == sorted(coarse, reverse=True)


def test_astm_grain_size_refuses_what_it_cannot_convert() -> None:
    assert astm_grain_size_number(50.0, "um") == pytest.approx(
        astm_grain_size_number(50.0, "µm")
    ), "both micron spellings"
    assert math.isnan(astm_grain_size_number(50.0, "furlong"))
    assert math.isnan(astm_grain_size_number(0.0, "nm"))


# ── calc/grain_edit (ADR 0005 §1 lift) ────────────────────────────────


def test_clip_clicks_uses_bankers_rounding_and_keeps_order() -> None:
    """The GUI has always used int(round(...)); np.round and int(x+0.5)
    disagree at .5 and would move a click onto a neighbouring grain."""
    from fermiviewer.calc.grain_edit import clip_clicks

    # (x, y) in -> (row, col) out; 2.5 -> 2 (half-to-even), 3.5 -> 4
    assert clip_clicks([(2.5, 3.5), (0.4, 0.6)], (10, 10)) == [(4, 2), (1, 0)]
    # out-of-bounds dropped, survivors keep their relative order
    assert clip_clicks([(99, 1), (3, 4), (-5, 2)], (10, 10)) == [(4, 3)]


def test_edit_grains_requires_matching_shapes() -> None:
    """The route fetched labels and raster from two different session
    entries and never checked; a mismatch surfaced deep inside watershed."""
    import numpy as np
    import pytest

    from fermiviewer.calc.grain_edit import edit_grains

    labels = np.ones((8, 8), dtype=np.int64)
    with pytest.raises(ValueError, match="must have the same shape"):
        edit_grains(labels, np.zeros((4, 4)), "split", [(1.0, 1.0)])


def test_edit_grains_rejects_an_empty_click_set_and_a_background_click() -> None:
    import numpy as np
    import pytest

    from fermiviewer.calc.grain_edit import edit_grains

    labels = np.zeros((8, 8), dtype=np.int64)
    labels[1:4, 1:4] = 1
    image = np.zeros((8, 8))

    with pytest.raises(ValueError, match="no points inside the image"):
        edit_grains(labels, image, "split", [(99.0, 99.0)])
    with pytest.raises(ValueError, match="not on a grain"):
        edit_grains(labels, image, "split", [(6.0, 6.0)])  # background pixel


def test_merging_non_adjacent_grains_leaves_them_separate() -> None:
    """merge_labels_at rewrites BY LABEL, then connectivity enforcement
    splits the disconnected pieces apart again — the pair comes back as two
    grains with fresh ids, not one. That interaction is the semantics."""
    import numpy as np

    from fermiviewer.calc.grain_edit import edit_grains

    labels = np.zeros((10, 10), dtype=np.int64)
    labels[1:3, 1:3] = 1
    labels[7:9, 7:9] = 2  # nowhere near grain 1
    image = np.zeros((10, 10))

    edit = edit_grains(labels, image, "merge", [(1.0, 1.0), (7.0, 7.0)])

    assert edit.op == "merge"
    assert len(set(edit.labels[edit.labels > 0].tolist())) == 2
    # and they are still the same two regions, just renumbered
    assert edit.labels[1, 1] != edit.labels[7, 7]


def test_merge_needs_two_distinct_grains() -> None:
    import numpy as np
    import pytest

    from fermiviewer.calc.grain_edit import edit_grains

    labels = np.zeros((8, 8), dtype=np.int64)
    labels[1:5, 1:5] = 1
    with pytest.raises(ValueError, match="≥2 distinct grains"):
        edit_grains(labels, np.zeros((8, 8)), "merge", [(1.0, 1.0), (2.0, 2.0)])


def test_orientation_is_measured_from_the_row_axis() -> None:
    """The convention, pinned because it is 90 degrees from the one most
    readers assume and nothing else in the tree would catch a flip.

    skimage measures the major axis from the ROW axis; a horizontal
    feature therefore reports pi/2, not 0. A consumer that assumed "from
    horizontal" would draw every elongated particle across its own short
    axis, and every value would still look plausible.
    """
    import numpy as np

    from fermiviewer.calc.shape_metrics import shape_descriptors

    def ellipse(angle_from_col_deg: float, n: int = 401) -> np.ndarray:
        t = np.radians(angle_from_col_deg)
        y, x = np.mgrid[-(n // 2) : n // 2 + 1, -(n // 2) : n // 2 + 1]
        xr = x * np.cos(t) + y * np.sin(t)
        yr = -x * np.sin(t) + y * np.cos(t)
        return (((xr / 80.0) ** 2 + (yr / 20.0) ** 2) <= 1).astype(np.int64)

    for from_col in (0.0, 30.0, 60.0, 90.0):
        got = float(
            np.degrees(np.asarray(shape_descriptors(ellipse(from_col)).orientation_rad)[0])
        )
        assert got == pytest.approx(90.0 - from_col, abs=0.1), from_col


def test_astm_is_counted_from_density_not_inferred_from_a_mean_diameter() -> None:
    """E112's planimetric method is grains per unit AREA, and both numbers
    are in hand — so `grain_report` counts instead of going through a mean
    equivalent diameter.

    The two agree only when every grain is the same size. Once they vary,
    `4/(pi*mean(d)**2)` exceeds the true `1/mean(area)` by Jensen's
    inequality, biasing G upward — reporting the microstructure as finer
    than it is. This builds grains of two deliberately different sizes so
    the two routes MUST disagree, and asserts the report follows the
    counted one.
    """
    import numpy as np

    from fermiviewer.calc.grain_report import grain_report
    from fermiviewer.calc.grain_size import astm_grain_size_from_density

    # four 20x20 grains and four 60x60 grains, tiled with no gaps
    labels = np.zeros((120, 240), dtype=np.int64)
    nxt = 1
    for r in range(0, 80, 20):
        for c in range(0, 40, 20):
            labels[r : r + 20, c : c + 20] = nxt
            nxt += 1
    for r in range(0, 120, 60):
        for c in range(60, 180, 60):
            labels[r : r + 60, c : c + 60] = nxt
            nxt += 1

    px_um, px_area_um2 = 1.0, 1.0
    report = grain_report(
        labels, labels.astype(np.float64), pixel_size=px_um,
        pixel_area=px_area_um2, unit="um",
    )

    total_um2 = float(report.area_px.sum()) * px_area_um2
    counted = astm_grain_size_from_density(
        report.n_grains / (total_um2 * 1e-6)          # um^2 -> mm^2
    )
    assumed = astm_grain_size_number(float(report.diameter_calibrated.mean()), "um")

    assert report.astm_grain_size == pytest.approx(counted, abs=1e-9)
    assert assumed > counted + 0.1, (
        "with grains of two sizes the mean-diameter route must read finer"
    )
