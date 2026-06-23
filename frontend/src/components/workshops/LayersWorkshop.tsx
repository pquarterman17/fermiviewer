// Cross-section / Layers workshop (PLAN_CROSS_SECTION_LAYERS Tier 1 #3):
// auto-orient + measure layer thicknesses and interface sharpness (σ_erf)
// from a cross-sectional EM image. Depth-profile plot marks the detected
// interfaces; the table reports thickness ± σ_erf with CSV export.

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  analyzeLayers,
  analyzeLayersMulti,
  applyFilter,
  editLayers,
  type LayersMultiResult,
  type LayersResult,
} from "../../lib/api";
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
  const setLayersOverlay = useViewer((s) => s.setLayersOverlay);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const setActive = useViewer((s) => s.setActive);
  const layersEdit = useViewer((s) => s.layersEdit);
  const setLayersEdit = useViewer((s) => s.setLayersEdit);
  const layersEditReq = useViewer((s) => s.layersEditReq);
  const setLayersEditReq = useViewer((s) => s.setLayersEditReq);

  const [axis, setAxis] = useState<"auto" | "y" | "x">("auto");
  const [modality, setModality] = useState<"haadf" | "eels" | "bf" | "df">("haadf");
  const [sensitivity, setSensitivity] = useState("0.3");
  const [nLayers, setNLayers] = useState("");
  const [waviness, setWaviness] = useState(false);
  const [result, setResult] = useState<LayersResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [addPos, setAddPos] = useState("");
  const images = useViewer((s) => s.images);
  const order = useViewer((s) => s.order);
  const [selectedMaps, setSelectedMaps] = useState<string[]>([]);
  const [multi, setMulti] = useState<LayersMultiResult | null>(null);
  const [multiBusy, setMultiBusy] = useState(false);

  const isImage = meta?.kind === "image";
  const mapIds = order.filter((id) => images[id]?.kind === "image");

  const toggleMap = (id: string) =>
    setSelectedMaps((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const runMulti = () => {
    // the active image is the reference (first); add the other selected maps
    const ids = [
      ...(activeId ? [activeId] : []),
      ...selectedMaps.filter((id) => id !== activeId),
    ];
    if (ids.length === 0) return;
    setMultiBusy(true);
    analyzeLayersMulti(ids, { reference: 0, modality, waviness: true })
      .then(setMulti)
      .catch((e: Error) => setStatus(`Layers multi: ${e.message}`))
      .finally(() => setMultiBusy(false));
  };

  const mean = (xs: (number | null)[]): number | null => {
    const v = xs.filter((x): x is number => x != null);
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  };

  // set the result + stage overlay + status from any (analyze or edit) response
  const applyResult = (r: LayersResult, imageId: string | null = activeId) => {
    setResult(r);
    if (imageId) {
      setLayersOverlay({
        imageId,
        axis: r.axis,
        interfaces: r.interfaces.map((i) => i.position),
        traces: r.interfaces.map((i) => i.trace),
      });
    }
    setStatus(
      `Layers: ${r.layers.length} layer(s), ${r.interfaces.length} interface(s)` +
        ` · ${r.axis}-axis · tilt ${r.tilt_deg == null ? "?" : r.tilt_deg.toFixed(1)}°`,
    );
  };

  // rotate the image so layers become axis-aligned, then re-analyze it
  const levelImage = () => {
    if (!activeId || !result || result.tilt_deg == null) return;
    const angle = result.tilt_deg;     // + tilt levels (verified by the route test)
    setBusy(true);
    applyFilter(activeId, "rotate", { angle })
      .then((meta) => {
        ingestDerived([meta]);
        setActive(meta.id);
        return analyzeLayers(meta.id, {
          axis,
          modality,
          sensitivity: Number(sensitivity) || 0.3,
          nLayers: Number(nLayers) || 0,
          waviness,
        }).then((r) => applyResult(r, meta.id));
      })
      .catch((e: Error) => setStatus(`Level: ${e.message}`))
      .finally(() => setBusy(false));
  };

  // recompute from an edited interface list (add / remove)
  const recompute = (positions: number[]) => {
    if (!activeId || !result) return;
    setBusy(true);
    editLayers(activeId, positions, {
      axis: result.axis === "x" ? "x" : "y",
      waviness,
    })
      .then(applyResult)
      .catch((e: Error) => setStatus(`Layers edit: ${e.message}`))
      .finally(() => setBusy(false));
  };

  // clear any prior overlay + edit state when the image changes / unmounts
  useEffect(() => {
    setResult(null);
    setLayersOverlay(null);
    setLayersEdit(false);
    setLayersEditReq(null);
  }, [activeId, setLayersOverlay, setLayersEdit, setLayersEditReq]);
  useEffect(
    () => () => {
      setLayersOverlay(null);
      setLayersEdit(false);
      setLayersEditReq(null);
    },
    [setLayersOverlay, setLayersEdit, setLayersEditReq],
  );

  // a stage edit (drag / add / remove) published a new interface list → recompute
  useEffect(() => {
    if (layersEditReq && result) {
      recompute(layersEditReq);
      setLayersEditReq(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layersEditReq]);

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
      .then(applyResult)
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
        <div className="fvd-ws-row">
          <span className="k" style={{ flex: 1 }}>
            {result.layers_horizontal ? "Horizontal" : "Vertical"} layers ({result.axis}-axis)
            {result.tilt_deg != null && `, tilt ${result.tilt_deg.toFixed(1)}°`}
            {result.coherence != null && ` · coh ${result.coherence.toFixed(2)}`}
          </span>
          {result.tilt_deg != null && Math.abs(result.tilt_deg) > 0.5 && (
            <button
              className="fvd-btn"
              disabled={busy}
              title="Rotate the image so the layers are axis-aligned, then re-analyze"
              onClick={levelImage}
            >
              Level
            </button>
          )}
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
      {result && (
        <div className="fvd-ws-row">
          <label className="k" style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <input
              type="checkbox"
              checked={layersEdit}
              onChange={(e) => setLayersEdit(e.target.checked)}
            />
            edit on stage
          </label>
          <span className="k" style={{ fontSize: 10, opacity: 0.7 }}>
            drag a line to nudge · click to add · right-click to remove
          </span>
        </div>
      )}
      {result && result.interfaces.length === 0 && (
        <div className="fvd-ws-note">No interfaces detected — try a lower sensitivity.</div>
      )}

      {result && (
        <details style={{ marginTop: 4 }}>
          <summary style={{ cursor: "pointer", fontSize: 11, opacity: 0.85 }}>
            Edit interfaces ({result.interfaces.length})
          </summary>
          <div className="fvd-ws-note" style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {result.interfaces.map((i, k) => (
              <span
                key={k}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 2,
                  border: "1px solid var(--border)",
                  borderRadius: 4,
                  padding: "0 4px",
                }}
              >
                {i.position.toFixed(1)}
                <button
                  className="fvd-icon-btn"
                  title="Remove this interface + recompute"
                  disabled={busy}
                  onClick={() =>
                    recompute(
                      result.interfaces.filter((_, j) => j !== k).map((it) => it.position),
                    )
                  }
                >
                  ✕
                </button>
              </span>
            ))}
          </div>
          <div className="fvd-ws-row">
            <input
              value={addPos}
              placeholder="depth px"
              style={{ width: 64 }}
              title="Add an interface at this depth (px) and recompute"
              onChange={(e) => setAddPos(e.target.value)}
            />
            <button
              className="fvd-btn"
              disabled={busy || !addPos}
              onClick={() => {
                const p = Number(addPos);
                if (Number.isFinite(p)) {
                  recompute([...result.interfaces.map((it) => it.position), p]);
                  setAddPos("");
                }
              }}
            >
              Add
            </button>
          </div>
        </details>
      )}
      {result && result.layers.length > 0 && (
        <div className="fvd-ws-row">
          <button className="fvd-btn" onClick={() => exportCsv(result)} title="Export layers + interfaces as CSV">
            Export CSV
          </button>
        </div>
      )}

      <details style={{ marginTop: 6 }}>
        <summary style={{ cursor: "pointer", padding: "4px 0", fontWeight: 500 }}>
          Per-element comparison (multi-map)
        </summary>
        <div className="fvd-ws-note" style={{ fontSize: 11 }}>
          The active image is the reference; pick other element/score maps to
          measure the same interfaces on (per-element σ_erf vs σ_w).
        </div>
        <div style={{ maxHeight: 110, overflowY: "auto", margin: "2px 0" }}>
          {mapIds
            .filter((id) => id !== activeId)
            .map((id) => (
              <label
                key={id}
                className="k"
                style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}
              >
                <input
                  type="checkbox"
                  checked={selectedMaps.includes(id)}
                  onChange={() => toggleMap(id)}
                />
                {images[id]?.name ?? id}
              </label>
            ))}
        </div>
        <div className="fvd-ws-row">
          <button
            className="fvd-btn"
            disabled={multiBusy || !activeId}
            onClick={runMulti}
          >
            {multiBusy ? "Comparing…" : "Compare"}
          </button>
        </div>
        {multi && multi.maps.length > 0 && (
          <table className="fvd-ws-table">
            <thead>
              <tr>
                <th>Map</th>
                <th>σ_erf ({multi.unit})</th>
                <th>σ_w ({multi.unit})</th>
              </tr>
            </thead>
            <tbody>
              {multi.maps.map((m) => {
                const se = mean(m.interfaces.map((i) => i.sigma_erf));
                const sw = mean(m.interfaces.map((i) => i.sigma_w));
                return (
                  <tr key={m.image_id}>
                    <td title={m.name}>{m.name.length > 18 ? `${m.name.slice(0, 17)}…` : m.name}</td>
                    <td>{se == null ? "—" : se.toFixed(3)}</td>
                    <td>{sw == null ? "—" : sw.toFixed(3)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </details>
    </div>
  );
}
