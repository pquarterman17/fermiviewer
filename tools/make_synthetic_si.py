#!/usr/bin/env python3
"""Generate synthetic EDS / EELS spectrum-image cubes for GUI testing.

Writes real ``.hspy`` files, so they open through FermiViewer's normal file
path with no special mode — the loader, the element picker, the maps and the
quantifiers all see an ordinary cube. Each cube ships a ``.truth.json``
sidecar recording the composition and geometry that produced it, so a
quantification result can be checked against the answer instead of eyeballed.

Peak and edge positions come from the application's OWN tables
(``calc.eds.line_energy``, ``calc.eels.EELS_EDGES``). That is deliberate: a
generator with its own copy of the line energies would drift, and every
window in the GUI snaps to the app's table — synthetic peaks have to land
exactly there or the tool tests the wrong thing.

Usage
-----
    python tools/make_synthetic_si.py --preset eds-layers
    python tools/make_synthetic_si.py --preset all --out ~/eds-testdata
    python tools/make_synthetic_si.py --preset eds-layers --shape 128 128

Presets
-------
eds-layers     Cross-section: Si substrate / SiO2 / Al2O3 / Ta barrier / C cap,
               at 200 kV (TEM). The app picks Ta L (8.146 keV) at this beam
               energy, so the lines are well separated.
eds-overlap    The same stack at 10 kV, where the app's line selection drops
               Ta to its M line (1.710 keV) — 0.030 keV from Si K (1.740).
               That is the classic interference case: the two windows cannot
               be separated by simple integration.
eds-particles  Al2O3 matrix with Ta-rich and C-rich discs of varying size.
eels-layers    Core-loss cross-section over a power-law background:
               Si L23 / C K / Ti L23 / O K, with white lines on the L edges.

Which line a synthetic peak lands on is decided by the app's own overvoltage
rule, not by this file, so --beam-kv genuinely changes which lines appear.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fermiviewer.calc.eds import line_energy  # noqa: E402
from fermiviewer.calc.eels import EELS_EDGES  # noqa: E402

# Reference EDS detector resolution: FWHM at Mn Kα, and the standard
# silicon-drift broadening law FWHM(E)² = FWHM_ref² + 2.5·(E − E_ref), all in
# eV. 130 eV at Mn Kα is a typical modern SDD.
MN_KA_EV = 5895.0
FWHM_MN_EV = 130.0
FANO_SLOPE = 2.5


def detector_fwhm_kev(energy_kev: float) -> float:
    """SDD resolution at an energy, from the Mn Kα reference (keV)."""
    ev = energy_kev * 1000.0
    var = FWHM_MN_EV**2 + FANO_SLOPE * (ev - MN_KA_EV)
    return float(np.sqrt(max(var, 40.0**2)) / 1000.0)


@dataclass
class Phase:
    """A material region: a name, its composition, and where it sits."""

    name: str
    #: element symbol → atomic fraction (need not be normalised)
    composition: dict[str, float]
    #: (row_lo, row_hi, col_lo, col_hi) fractional bounds, or None for discs
    slab: tuple[float, float, float, float] | None = None
    #: (row, col, radius) fractional discs
    discs: list[tuple[float, float, float]] = field(default_factory=list)

    def mask(self, h: int, w: int) -> np.ndarray:
        yy, xx = np.mgrid[0:h, 0:w]
        fy, fx = (yy + 0.5) / h, (xx + 0.5) / w
        out = np.zeros((h, w), dtype=bool)
        if self.slab is not None:
            r0, r1, c0, c1 = self.slab
            out |= (fy >= r0) & (fy < r1) & (fx >= c0) & (fx < c1)
        for cy, cx, radius in self.discs:
            out |= (fy - cy) ** 2 + (fx - cx) ** 2 <= radius**2
        return out


@dataclass
class Preset:
    name: str
    modality: str  # "eds" | "eels"
    phases: list[Phase]
    beam_kv: float = 200.0
    #: energy axis: (offset, scale, channels, units)
    axis: tuple[float, float, int, str] = (0.0, 0.01, 2048, "keV")
    description: str = ""


def normalised(composition: dict[str, float]) -> dict[str, float]:
    total = sum(composition.values())
    return {k: v / total for k, v in composition.items()} if total else {}


PRESETS: dict[str, Preset] = {
    "eds-layers": Preset(
        name="eds-layers",
        modality="eds",
        description="Cross-section stack at 200 kV; well-separated lines.",
        phases=[
            Phase("Si substrate", {"Si": 1.0}, slab=(0.62, 1.0, 0.0, 1.0)),
            Phase("SiO2", {"Si": 1.0, "O": 2.0}, slab=(0.48, 0.62, 0.0, 1.0)),
            Phase("Ta barrier", {"Ta": 1.0}, slab=(0.42, 0.48, 0.0, 1.0)),
            Phase("Al2O3", {"Al": 2.0, "O": 3.0}, slab=(0.16, 0.42, 0.0, 1.0)),
            Phase("C cap", {"C": 1.0}, slab=(0.06, 0.16, 0.0, 1.0)),
            Phase("vacuum", {}, slab=(0.0, 0.06, 0.0, 1.0)),
        ],
    ),
    "eds-overlap": Preset(
        name="eds-overlap",
        modality="eds",
        beam_kv=10.0,
        # At 10 kV the overvoltage rule selects Ta M (1.710 keV) instead of
        # Ta L, putting it 0.030 keV from Si K (1.740) — closer than either
        # window is wide, so their maps contaminate each other.
        axis=(0.0, 0.005, 2048, "keV"),
        description="10 kV stack; Ta M (1.710) interferes with Si K (1.740).",
        phases=[
            Phase("Si substrate", {"Si": 1.0}, slab=(0.62, 1.0, 0.0, 1.0)),
            Phase("SiO2", {"Si": 1.0, "O": 2.0}, slab=(0.48, 0.62, 0.0, 1.0)),
            Phase("Ta barrier", {"Ta": 1.0}, slab=(0.42, 0.48, 0.0, 1.0)),
            Phase("Al2O3", {"Al": 2.0, "O": 3.0}, slab=(0.16, 0.42, 0.0, 1.0)),
            Phase("C cap", {"C": 1.0}, slab=(0.06, 0.16, 0.0, 1.0)),
            Phase("vacuum", {}, slab=(0.0, 0.06, 0.0, 1.0)),
        ],
    ),
    "eds-particles": Preset(
        name="eds-particles",
        modality="eds",
        description="Ta-rich and C-rich particles in an Al2O3 matrix.",
        phases=[
            Phase("Al2O3 matrix", {"Al": 2.0, "O": 3.0}, slab=(0.0, 1.0, 0.0, 1.0)),
            Phase(
                "Ta particles",
                {"Ta": 1.0, "O": 0.4},
                discs=[(0.30, 0.28, 0.11), (0.68, 0.60, 0.07), (0.44, 0.78, 0.05)],
            ),
            Phase(
                "C particles",
                {"C": 1.0},
                discs=[(0.72, 0.24, 0.09), (0.24, 0.66, 0.06)],
            ),
        ],
    ),
    "eels-layers": Preset(
        name="eels-layers",
        modality="eels",
        description="Core-loss cross-section over a power-law background.",
        # 0.5 eV/ch from 80 eV → 80–1103 eV. The start must sit BELOW the
        # lowest edge used (Si L23 at 99 eV) or that element is silently
        # dropped from the cube while still appearing in the phase list.
        axis=(80.0, 0.5, 2048, "eV"),
        phases=[
            Phase("Si substrate", {"Si": 1.0}, slab=(0.60, 1.0, 0.0, 1.0)),
            Phase("SiO2", {"Si": 1.0, "O": 2.0}, slab=(0.44, 0.60, 0.0, 1.0)),
            Phase("TiO2", {"Ti": 1.0, "O": 2.0}, slab=(0.20, 0.44, 0.0, 1.0)),
            Phase("C cap", {"C": 1.0}, slab=(0.08, 0.20, 0.0, 1.0)),
            Phase("vacuum", {}, slab=(0.0, 0.08, 0.0, 1.0)),
        ],
    ),
}


def _energy_axis(preset: Preset) -> np.ndarray:
    offset, scale, channels, _ = preset.axis
    return offset + scale * np.arange(channels, dtype=np.float64)


def _fraction_maps(
    preset: Preset, h: int, w: int
) -> tuple[dict[str, np.ndarray], np.ndarray, list[dict[str, object]]]:
    """Per-element atomic-fraction maps, an occupancy mask, and truth rows.

    Later phases paint over earlier ones, so a particle sitting on a matrix
    replaces it rather than adding to it.
    """
    fractions: dict[str, np.ndarray] = {}
    occupied = np.zeros((h, w), dtype=bool)
    rows: list[dict[str, object]] = []
    for phase in preset.phases:
        mask = phase.mask(h, w)
        for existing in fractions.values():
            existing[mask] = 0.0
        composition = normalised(phase.composition)
        for symbol, fraction in composition.items():
            fractions.setdefault(symbol, np.zeros((h, w)))[mask] = fraction
        if composition:
            occupied |= mask
        rows.append(
            {
                "phase": phase.name,
                "pixels": int(mask.sum()),
                "atomic_percent": {k: round(v * 100, 4) for k, v in composition.items()},
            }
        )
    return fractions, occupied, rows


def _eds_cube(
    preset: Preset, h: int, w: int, counts: float, rng: np.random.Generator
) -> tuple[np.ndarray, dict[str, np.ndarray], list[dict[str, object]], list[dict]]:
    energy = _energy_axis(preset)
    fractions, occupied, rows = _fraction_maps(preset, h, w)
    e0 = preset.beam_kv

    # Kramers continuum, one shape for the whole cube; only its amplitude
    # varies with how much material a pixel contains.
    # Kramers goes as (E0 − E)/E, which diverges at E → 0. The denominator is
    # floored at the detector's low-energy limit rather than at an epsilon:
    # 1/1e-6 puts a spike ~10^8 in channel 0, and since the peak finder
    # thresholds at a fraction of the spectrum maximum, that one bogus channel
    # raised the floor above every real line and auto-ID stopped seeing Ta.
    cutoff = 0.10
    with np.errstate(divide="ignore", invalid="ignore"):
        continuum = np.where(
            energy < e0,
            np.maximum(e0 - energy, 0.0) / np.maximum(energy, cutoff),
            0.0,
        )
    # Detector low-energy roll-off. It has to be smooth: a hard
    # `continuum[energy < 0.15] = 0` leaves a step whose edge the peak finder
    # reads as a real line (it was confidently identifying boron at 0.16 keV
    # in a cube containing none).
    continuum *= 1.0 / (1.0 + np.exp(-(energy - 0.20) / 0.035))
    continuum /= continuum.sum() or 1.0

    signal = np.zeros((h, w, energy.size))
    lines: list[dict] = []
    for symbol, fraction_map in sorted(fractions.items()):
        e_line, line = line_energy(symbol, beam_kv=e0)
        if not np.isfinite(e_line):
            continue
        sigma = detector_fwhm_kev(e_line) / 2.3548
        shape = np.exp(-0.5 * ((energy - e_line) / sigma) ** 2)
        shape /= shape.sum() or 1.0
        # Heavier elements fluoresce more efficiently at a fixed beam energy;
        # a mild Z weighting keeps a trace heavy element from vanishing.
        yield_weight = 1.0 + 0.5 * np.log1p(e_line)
        signal += fraction_map[:, :, None] * yield_weight * shape[None, None, :]
        lines.append(
            {
                "symbol": symbol,
                "line": line,
                "energy_kev": round(float(e_line), 4),
                "fwhm_kev": round(detector_fwhm_kev(e_line), 4),
                "mean_atomic_fraction": round(float(fraction_map.mean()), 6),
            }
        )

    peak_total = signal.sum(axis=2, keepdims=True)
    background = occupied[:, :, None] * continuum[None, None, :] * peak_total * 0.6
    lam = (signal + background) * counts
    cube = rng.poisson(lam).astype(np.uint16)
    return cube, fractions, rows, lines


def _eels_cube(
    preset: Preset, h: int, w: int, counts: float, rng: np.random.Generator
) -> tuple[np.ndarray, dict[str, np.ndarray], list[dict[str, object]], list[dict]]:
    energy = _energy_axis(preset)
    fractions, occupied, rows = _fraction_maps(preset, h, w)

    # Power-law pre-edge background, the thing every EELS background model
    # is written to remove.
    background = (energy / energy[0]) ** -3.0
    background /= background.sum() or 1.0

    signal = np.zeros((h, w, energy.size))
    edges: list[dict] = []
    by_element: dict[str, list] = {}
    for edge in EELS_EDGES:
        by_element.setdefault(edge.element, []).append(edge)

    for symbol, fraction_map in sorted(fractions.items()):
        candidates = [e for e in by_element.get(symbol, []) if energy[0] < e.onset_ev < energy[-1]]
        if not candidates:
            continue
        edge = min(candidates, key=lambda e: e.onset_ev)
        above = energy >= edge.onset_ev
        shape = np.zeros_like(energy)
        # Hydrogenic-style sawtooth: sharp onset, power-law decay after it.
        shape[above] = (energy[above] / edge.onset_ev) ** -2.6
        if edge.edge.startswith("L"):
            # L23 white lines — the sharp pair right at the onset
            for offset, weight in ((1.5, 1.0), (7.0, 0.55)):
                centre = edge.onset_ev + offset
                shape += weight * 1.6 * np.exp(-0.5 * ((energy - centre) / 2.2) ** 2)
        total = shape.sum()
        if total <= 0:
            continue
        shape /= total
        signal += fraction_map[:, :, None] * shape[None, None, :]
        edges.append(
            {
                "symbol": symbol,
                "edge": edge.edge,
                "onset_ev": float(edge.onset_ev),
                "mean_atomic_fraction": round(float(fraction_map.mean()), 6),
            }
        )

    thickness = occupied[:, :, None].astype(float)
    lam = (signal * 0.35 + thickness * background[None, None, :]) * counts
    cube = rng.poisson(lam).astype(np.uint16)
    return cube, fractions, rows, edges


def write_hspy(
    path: Path, cube: np.ndarray, preset: Preset, elements: list[str]
) -> None:
    """Write a minimal HyperSpy-layout HDF5 the .hspy reader understands."""
    offset, scale, _, units = preset.axis
    h, w, _ = cube.shape
    with h5py.File(path, "w") as f:
        exp = f.create_group(f"Experiments/{preset.name}")
        exp.create_dataset("data", data=cube, compression="gzip", compression_opts=4)
        for index, (size, sc, off, unit, axis_name, navigate) in enumerate(
            [
                (h, 1.0, 0.0, "nm", "y", True),
                (w, 1.0, 0.0, "nm", "x", True),
                (cube.shape[2], scale, offset, units, "Energy", False),
            ]
        ):
            axis = exp.create_group(f"axis-{index}")
            axis.attrs["size"] = size
            axis.attrs["scale"] = sc
            axis.attrs["offset"] = off
            axis.attrs["units"] = unit
            axis.attrs["name"] = axis_name
            axis.attrs["navigate"] = navigate
        sample = exp.create_group("metadata/Sample")
        sample.attrs["elements"] = np.array(elements, dtype=h5py.special_dtype(vlen=str))
        exp.create_group("metadata/General").attrs["title"] = preset.name


def build(
    preset: Preset, shape: tuple[int, int], counts: float, seed: int, out_dir: Path
) -> tuple[Path, dict]:
    h, w = shape
    rng = np.random.default_rng(seed)
    make = _eds_cube if preset.modality == "eds" else _eels_cube
    cube, fractions, phase_rows, species = make(preset, h, w, counts, rng)

    elements = sorted(fractions)
    out_dir.mkdir(parents=True, exist_ok=True)
    cube_path = out_dir / f"synthetic_{preset.name.replace('-', '_')}.hspy"
    write_hspy(cube_path, cube, preset, elements)

    offset, scale, channels, units = preset.axis
    truth = {
        "preset": preset.name,
        "modality": preset.modality,
        "description": preset.description,
        "shape": [h, w, channels],
        "energy_axis": {
            "offset": offset,
            "scale": scale,
            "channels": channels,
            "units": units,
            "range": [offset, offset + scale * (channels - 1)],
        },
        "beam_kv": preset.beam_kv,
        "counts_scale": counts,
        "seed": seed,
        "elements": elements,
        "species": species,
        "phases": phase_rows,
        "field_mean_atomic_percent": {
            symbol: round(float(fraction.mean()) * 100, 4)
            for symbol, fraction in sorted(fractions.items())
        },
        "total_counts": int(cube.sum()),
    }
    truth_path = cube_path.with_suffix(".truth.json")
    truth_path.write_text(json.dumps(truth, indent=2) + "\n")
    return cube_path, truth


def _report(path: Path, truth: dict) -> None:
    size_mb = path.stat().st_size / 1e6
    shape = "×".join(str(n) for n in truth["shape"])
    print(f"\nwrote  {path.name}   ({shape}, {size_mb:.1f} MB)")
    key = "energy_kev" if truth["modality"] == "eds" else "onset_ev"
    unit = "keV" if truth["modality"] == "eds" else "eV"
    for s in truth["species"]:
        marker = s.get("line") or s.get("edge")
        pct = truth["field_mean_atomic_percent"][s["symbol"]]
        print(
            f"  {s['symbol']:<3} {marker:<4} {s[key]:>8.3f} {unit}"
            f"   field at% {pct:6.2f}"
        )
    print(f"  ground truth → {path.with_suffix('.truth.json').name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--preset",
        default="eds-layers",
        choices=[*PRESETS, "all"],
        help="which synthetic dataset to build (default: eds-layers)",
    )
    parser.add_argument(
        "--shape",
        nargs=2,
        type=int,
        default=(64, 64),
        metavar=("ROWS", "COLS"),
        help="spatial size (default: 64 64)",
    )
    parser.add_argument(
        "--counts",
        type=float,
        default=4000.0,
        help="counts per pixel scale — lower is noisier (default: 4000)",
    )
    parser.add_argument(
        "--beam-kv",
        type=float,
        default=None,
        help="override the preset's beam energy; changes which X-ray lines "
        "the app selects (e.g. 10 puts Ta on its M line)",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path.cwd() / "synthetic-data",
        help="output directory (default: ./synthetic-data)",
    )
    args = parser.parse_args(argv)

    names = list(PRESETS) if args.preset == "all" else [args.preset]
    for name in names:
        preset = PRESETS[name]
        if args.beam_kv is not None:
            preset = replace(preset, beam_kv=args.beam_kv)
        path, truth = build(
            preset, tuple(args.shape), args.counts, args.seed, args.out
        )
        _report(path, truth)
    print(f"\nOpen these in FermiViewer with File → Open. Output dir: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
