// CSV text for a layers / cross-section result.
//
// Split out of `layers/LayerStack.tsx` so the Layers workshop and the
// Cross-section Report step build the SAME bytes from the same result. They
// were one inline blob-and-click inside a presentational component, which is
// how a second caller ends up hand-rolling a nearly-identical table that
// drifts a column at a time.
//
// Text in, download out: these return strings so a caller chooses the
// filename (and so a test can assert on content without a DOM download).

import { type LayersResult } from "./api";

const fixed = (v: number | null | undefined, digits: number): string =>
  v == null ? "" : v.toFixed(digits);

/** Layer bands and their interfaces, one table each, blank line between. */
export function layersCsvText(r: LayersResult): string {
  const rows: (string | number)[][] = [
    ["layer", "top_px", "bottom_px", `thickness_${r.unit}`, `thickness_std_${r.unit}`],
    ...r.layers.map((l) => [
      l.index,
      l.top.toFixed(3),
      l.bottom.toFixed(3),
      l.thickness.toFixed(4),
      fixed(l.thickness_std, 4),
    ]),
    [],
    [
      "interface", "position_px", `sigma_erf_${r.unit}`, `sigma_w_${r.unit}`,
      "r_squared", `sigma_w_ci_lo_${r.unit}`, `sigma_w_ci_hi_${r.unit}`,
      "trace_quality", `noise_floor_${r.unit}`, `xi_${r.unit}`, "hurst",
      `sigma_chem_${r.unit}`,
    ],
    ...r.interfaces.map((i, k) => [
      k,
      i.position.toFixed(3),
      fixed(i.sigma_erf, 4),
      fixed(i.sigma_w, 4),
      i.r_squared.toFixed(4),
      fixed(i.roughness?.sigma_ci?.[0], 4),
      fixed(i.roughness?.sigma_ci?.[1], 4),
      fixed(i.roughness?.quality, 3),
      fixed(i.roughness?.noise_floor, 4),
      fixed(i.roughness?.xi, 2),
      fixed(i.roughness?.hurst, 3),
      fixed(i.roughness?.sigma_chem, 4),
    ]),
  ];
  return rows.map((row) => row.join(",")).join("\n");
}

/**
 * The depth profile the interfaces were found in, as it was integrated.
 *
 * The layer table alone cannot be replotted or re-fitted elsewhere -- it is
 * the conclusion, not the measurement. This is the measurement: the same
 * `depth_pos`/`depth_profile` arrays the on-screen plot draws, so a reader
 * can check where an interface was placed against the data that placed it.
 */
export function profileCsvText(r: LayersResult): string {
  const header = [`depth_${r.unit ?? "px"}`, "intensity"].join(",");
  const n = Math.min(r.depth_pos.length, r.depth_profile.length);
  const rows = Array.from({ length: n }, (_, i) =>
    `${r.depth_pos[i]},${r.depth_profile[i]}`);
  return [header, ...rows].join("\n");
}
