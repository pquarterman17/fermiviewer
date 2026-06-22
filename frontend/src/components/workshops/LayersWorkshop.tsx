// Cross-section / Layers workshop (PLAN_CROSS_SECTION_LAYERS Tier 1 #3):
// auto-orient + measure layer thicknesses and interface sharpness (σ_erf)
// from a cross-sectional EM image. Depth-profile plot marks the detected
// interfaces; the table reports thickness ± σ_erf with CSV export.

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import { analyzeLayers, type LayersResult } from "../../lib/api";
import { useViewer } from "../../store/viewer";

function DepthPlot({ r }: { r: LayersResult }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    plotRef.current?.destroy();
    const accent =
      getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() ||
      "#a78bfa";
    const interfaces = r.interfaces.map((i) => i.position);
    plotRef.current = new uPlot(
      {
        width: host.clientWidth || 300,
        height: 160,
        series: [
          { label: "depth (px)" },
          { label: "I", stroke: accent, width: 1.5, points: { show: false } },
        ],
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
        ],
        legend: { show: false },
        cursor: { y: false },
        hooks: {
          draw: [
            (u) => {
              const ctx = u.ctx;
              ctx.save();
              ctx.strokeStyle = "#f59e0b";
              ctx.setLineDash([4, 3]);
              ctx.lineWidth = 1;
              for (const p of interfaces) {
                const x = u.valToPos(p, "x", true);
                ctx.beginPath();
                ctx.moveTo(x, u.bbox.top);
                ctx.lineTo(x, u.bbox.top + u.bbox.height);
                ctx.stroke();
              }
              ctx.restore();
            },
          ],
        },
      },
      [r.depth_pos, r.depth_profile] as uPlot.AlignedData,
      host,
    );
    const ro = new ResizeObserver(() => {
      if (plotRef.current && host.clientWidth > 0) {
        plotRef.current.setSize({ width: host.clientWidth, height: 160 });
      }
    });
    ro.observe(host);
    return () => {
      ro.disconnect();
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [r]);

  return <div ref={hostRef} className="fvd-ws-plot" />;
}

function exportCsv(r: LayersResult) {
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
    ["interface", "position_px", `sigma_erf_${r.unit}`, `sigma_w_${r.unit}`, "r_squared"],
    ...r.interfaces.map((i, k) => [
      k,
      i.position.toFixed(3),
      i.sigma_erf == null ? "" : i.sigma_erf.toFixed(4),
      i.sigma_w == null ? "" : i.sigma_w.toFixed(4),
      i.r_squared.toFixed(4),
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

export default function LayersWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) => (s.activeId ? (s.images[s.activeId] ?? null) : null));
  const setStatus = useViewer((s) => s.setStatus);

  const [axis, setAxis] = useState<"auto" | "y" | "x">("auto");
  const [modality, setModality] = useState<"haadf" | "eels" | "bf" | "df">("haadf");
  const [sensitivity, setSensitivity] = useState("0.3");
  const [nLayers, setNLayers] = useState("");
  const [waviness, setWaviness] = useState(false);
  const [result, setResult] = useState<LayersResult | null>(null);
  const [busy, setBusy] = useState(false);

  const isImage = meta?.kind === "image";

  useEffect(() => {
    setResult(null);
  }, [activeId]);

  const run = () => {
    if (!activeId) return;
    setBusy(true);
    analyzeLayers(activeId, {
      axis,
      modality,
      sensitivity: Number(sensitivity) || 0.3,
      nLayers: Number(nLayers) || 0,
      waviness,
    })
      .then((r) => {
        setResult(r);
        setStatus(
          `Layers: ${r.layers.length} layer(s), ${r.interfaces.length} interface(s)` +
            ` · ${r.axis}-axis · tilt ${r.tilt_deg == null ? "?" : r.tilt_deg.toFixed(1)}°`,
        );
      })
      .catch((e: Error) => setStatus(`Layers: ${e.message}`))
      .finally(() => setBusy(false));
  };

  if (!isImage) {
    return (
      <div className="fvd-ws-empty">
        Select a 2-D image (derive an element/score map from a cube first).
      </div>
    );
  }

  return (
    <div className="fvd-ws">
      <div className="fvd-ws-row">
        <span className="k">Axis</span>
        <div className="fvd-seg">
          {(["auto", "y", "x"] as const).map((a) => (
            <button
              key={a}
              className={`fvd-seg-btn${axis === a ? " active" : ""}`}
              title={a === "auto" ? "auto-detect growth axis" : `layers stack along ${a}`}
              onClick={() => setAxis(a)}
            >
              {a}
            </button>
          ))}
        </div>
      </div>
      <div className="fvd-ws-row">
        <span className="k">Modality</span>
        <div className="fvd-seg">
          {(["haadf", "eels", "bf", "df"] as const).map((m) => (
            <button
              key={m}
              className={`fvd-seg-btn${modality === m ? " active" : ""}`}
              title={
                m === "bf" || m === "df"
                  ? "scale-space interface detection (rejects thickness fringes)"
                  : `${m} (intensity-step detection)`
              }
              onClick={() => setModality(m)}
            >
              {m.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <div className="fvd-ws-row">
        <span className="k">Sensitivity</span>
        <input
          value={sensitivity}
          style={{ width: 48 }}
          title="Interface peak threshold (fraction of max gradient) — lower finds more"
          onChange={(e) => setSensitivity(e.target.value)}
        />
        <span className="k"># layers</span>
        <input
          value={nLayers}
          placeholder="auto"
          style={{ width: 44 }}
          title="Optional hint: keep only the (n−1) strongest interfaces"
          onChange={(e) => setNLayers(e.target.value)}
        />
        <button className="fvd-btn" onClick={run} disabled={busy || !activeId}>
          {busy ? "Analyzing…" : "Analyze"}
        </button>
      </div>
      <div className="fvd-ws-row">
        <label className="k" style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <input
            type="checkbox"
            checked={waviness}
            onChange={(e) => setWaviness(e.target.checked)}
          />
          waviness (σ_w)
        </label>
        <span className="k" style={{ fontSize: 10, opacity: 0.7 }}>
          column-by-column interface trace — geometric roughness + thickness ±std
        </span>
      </div>

      {result && (
        <div className="fvd-ws-note">
          {result.layers_horizontal ? "Horizontal" : "Vertical"} layers ({result.axis}-axis)
          {result.tilt_deg != null && `, tilt ${result.tilt_deg.toFixed(1)}°`}
          {result.coherence != null && ` · coherence ${result.coherence.toFixed(2)}`}
        </div>
      )}
      {result && result.depth_pos.length > 0 && <DepthPlot r={result} />}

      {result && result.layers.length > 0 && (
        <table className="fvd-ws-table">
          <thead>
            <tr>
              <th>Layer</th>
              <th>Thickness ({result.unit})</th>
              <th>σ_erf ({result.unit})</th>
              <th>σ_w ({result.unit})</th>
            </tr>
          </thead>
          <tbody>
            {result.layers.map((l) => {
              const top = result.interfaces[l.index];
              return (
                <tr key={l.index}>
                  <td>{l.index + 1}</td>
                  <td>
                    {l.thickness.toFixed(2)}
                    {l.thickness_std != null && ` ± ${l.thickness_std.toFixed(2)}`}
                  </td>
                  <td>{top?.sigma_erf == null ? "—" : top.sigma_erf.toFixed(3)}</td>
                  <td>{top?.sigma_w == null ? "—" : top.sigma_w.toFixed(3)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {result && result.interfaces.length === 0 && (
        <div className="fvd-ws-note">No interfaces detected — try a lower sensitivity.</div>
      )}
      {result && result.layers.length > 0 && (
        <div className="fvd-ws-row">
          <button className="fvd-btn" onClick={() => exportCsv(result)} title="Export layers + interfaces as CSV">
            Export CSV
          </button>
        </div>
      )}
    </div>
  );
}
