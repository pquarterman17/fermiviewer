// LayerStack band diagram + CSV export, split out of LayersWorkshop.tsx
// (repo-health #33). Moved verbatim; only the import path now points one
// directory up.

import { Fragment } from "react";

import { type LayersResult } from "../../../lib/api";

// Per-band band colors — data colors (like false-color overlays), not chrome.
// Mirrors the design system's layer-stack palette (WS5b).
const LAYER_COLORS = [
  "#8b7bd8",
  "#38b6c4",
  "#e0a13a",
  "#3fbf87",
  "#d96a9a",
  "#6f9bd8",
];

// A proportional band diagram of the detected stack: each layer sized by its
// thickness and labelled with thickness ± std, each inter-layer boundary
// annotated with its interface sharpness σ_erf. Purely a re-presentation of
// the analyze/layers result — the same numbers appear in the table below — so
// the stack picture sits beside the values (WS5b Cross-section redesign).
export function LayerStack({ r }: { r: LayersResult }) {
  const layers = r.layers;
  // interfaces[layer.index] is the interface at the top of that layer (the
  // same mapping the results table uses), so the boundary between rendered
  // band i and band i+1 is the top interface of band i+1.
  const boundary = (bandIdx: number) => r.interfaces[layers[bandIdx].index];
  return (
    <div className="fvd-layerstack">
      <div className="fvd-layerstack-bands">
        {layers.map((l, i) => (
          <div
            key={l.index}
            className="fvd-layerstack-band"
            style={{
              flexGrow: Math.max(l.thickness, 1e-3),
              background: LAYER_COLORS[i % LAYER_COLORS.length],
            }}
          >
            <span>{l.thickness.toFixed(1)}</span>
          </div>
        ))}
      </div>
      <div className="fvd-layerstack-labels">
        {layers.map((l, i) => {
          const below = i < layers.length - 1 ? boundary(i + 1) : null;
          return (
            <Fragment key={l.index}>
              <div
                className="fvd-layerstack-label"
                style={{ flexGrow: Math.max(l.thickness, 1e-3) }}
              >
                <span
                  className="fvd-layerstack-chip"
                  style={{ background: LAYER_COLORS[i % LAYER_COLORS.length] }}
                />
                <span className="fvd-layerstack-name">Layer {l.index + 1}</span>
                <span className="fvd-layerstack-th">
                  {l.thickness.toFixed(1)}
                  {l.thickness_std != null && (
                    <span className="dim"> ±{l.thickness_std.toFixed(1)}</span>
                  )}{" "}
                  {r.unit}
                </span>
              </div>
              {below && (
                <div className="fvd-layerstack-iface">
                  <span className="rail" />
                  <span className="sig">
                    σ{" "}
                    {below.sigma_erf == null
                      ? "—"
                      : below.sigma_erf.toFixed(2)}
                  </span>
                </div>
              )}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

export function exportCsv(r: LayersResult) {
  const rows: (string | number)[][] = [
    ["layer", "top_px", "bottom_px", `thickness_${r.unit}`, `thickness_std_${r.unit}`],
    ...r.layers.map((l) => [
      l.index,
      l.top.toFixed(3),
      l.bottom.toFixed(3),
      l.thickness.toFixed(4),
      l.thickness_std == null ? "" : l.thickness_std.toFixed(4),
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
      i.sigma_erf == null ? "" : i.sigma_erf.toFixed(4),
      i.sigma_w == null ? "" : i.sigma_w.toFixed(4),
      i.r_squared.toFixed(4),
      i.roughness?.sigma_ci == null ? "" : i.roughness.sigma_ci[0].toFixed(4),
      i.roughness?.sigma_ci == null ? "" : i.roughness.sigma_ci[1].toFixed(4),
      i.roughness == null ? "" : i.roughness.quality.toFixed(3),
      i.roughness?.noise_floor == null ? "" : i.roughness.noise_floor.toFixed(4),
      i.roughness?.xi == null ? "" : i.roughness.xi.toFixed(2),
      i.roughness?.hurst == null ? "" : i.roughness.hurst.toFixed(3),
      i.roughness?.sigma_chem == null ? "" : i.roughness.sigma_chem.toFixed(4),
    ]),
  ];
  const csv = rows.map((row) => row.join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "layers.csv";
  a.click();
  URL.revokeObjectURL(url);
}
