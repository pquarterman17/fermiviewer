// Cross-section / Layers workshop (PLAN_CROSS_SECTION_LAYERS Tier 1 #3):
// auto-orient + measure layer thicknesses and interface sharpness (σ_erf)
// from a cross-sectional EM image. Depth-profile plot marks the detected
// interfaces; the table reports thickness ± σ_erf with CSV export.

import { Fragment, useEffect, useState } from "react";

import {
  analyzeLayers,
  analyzeLayersMulti,
  applyFilter,
  editLayers,
  type LayersMultiResult,
  type LayersResult,
} from "../../lib/api";
import {
  layerOverlayCoordinates,
  roiLocalDepths,
  useAnalysisRoi,
  type AnalysisRoi,
} from "../../hooks/useAnalysisRoi";
import { useViewer } from "../../store/viewer";
import { assessLayerQuality } from "../../lib/analysisQuality";
import { AnalysisQualityCard } from "./AnalysisQualityCard";
import AnalysisRegionSelect from "./AnalysisRegionSelect";
import DepthPlot from "./LayersDepthPlot";
import LayersRoughnessDetail from "./LayersRoughnessDetail";

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
  const [decurtain, setDecurtain] = useState(false);
  const [foilT, setFoilT] = useState("");         // ≈ foil thickness, calibrated
  const [detailIdx, setDetailIdx] = useState<number | null>(null);
  const [result, setResult] = useState<LayersResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [addPos, setAddPos] = useState("");
  const layersFocusReq = useViewer((s) => s.layersFocusReq);
  const setLayersFocusReq = useViewer((s) => s.setLayersFocusReq);
  const images = useViewer((s) => s.images);
  const order = useViewer((s) => s.order);
  const [selectedMaps, setSelectedMaps] = useState<string[]>([]);
  const [multi, setMulti] = useState<LayersMultiResult | null>(null);
  const [multiBusy, setMultiBusy] = useState(false);
  const [qualityAccepted, setQualityAccepted] = useState(false);
  const analysisRoi = useAnalysisRoi(activeId, meta?.shape ?? []);
  const roiKey = analysisRoi.roi?.join(":") ?? "whole";

  const isImage = meta?.kind === "image";
  const mapIds = order.filter((id) => images[id]?.kind === "image");
  const layerQuality = result
    ? assessLayerQuality(result, Number(nLayers) || 0)
    : null;
  const canUseResult = layerQuality?.rating !== "poor" || qualityAccepted;

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
  const applyResult = (
    r: LayersResult,
    imageId: string | null = activeId,
    roi: AnalysisRoi | null = analysisRoi.roi,
  ) => {
    setResult(r);
    setQualityAccepted(false);
    setLayersEdit(false);
    if (imageId) {
      const overlay = layerOverlayCoordinates(
        r.axis,
        r.interfaces.map((i) => i.position),
        r.interfaces.map((i) => i.trace),
        roi,
      );
      setLayersOverlay({
        imageId,
        axis: r.axis,
        ...overlay,
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
          reduce: decurtain ? "median" : "mean",
          destripe: decurtain,
        }).then((r) => applyResult(r, meta.id, null));
      })
      .catch((e: Error) => setStatus(`Level: ${e.message}`))
      .finally(() => setBusy(false));
  };

  // recompute from an edited interface list (add / remove)
  const recompute = (positions: number[]) => {
    if (!activeId || !result) return;
    setBusy(true);
    editLayers(activeId, positions, {
      roi: analysisRoi.roi,
      axis: result.axis === "x" ? "x" : "y",
      waviness,
      reduce: decurtain ? "median" : "mean",
      destripe: decurtain,
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
    setDetailIdx(null);
    setQualityAccepted(false);
  }, [activeId, roiKey, setLayersOverlay, setLayersEdit, setLayersEditReq]);

  // a stage click on an interface line focuses its roughness detail card
  useEffect(() => {
    if (layersFocusReq != null) {
      setDetailIdx(layersFocusReq);
      setLayersFocusReq(null);
    }
  }, [layersFocusReq, setLayersFocusReq]);
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
      recompute(roiLocalDepths(result.axis, layersEditReq, analysisRoi.roi));
      setLayersEditReq(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layersEditReq]);

  const run = () => {
    if (!activeId) return;
    setBusy(true);
    analyzeLayers(activeId, {
      roi: analysisRoi.roi,
      axis,
      modality,
      sensitivity: Number(sensitivity) || 0.3,
      nLayers: Number(nLayers) || 0,
      waviness,
      reduce: decurtain ? "median" : "mean",
      destripe: decurtain,
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
      <AnalysisRegionSelect
        choice={analysisRoi.choice}
        options={analysisRoi.options}
        disabled={busy}
        onChange={analysisRoi.setChoice}
      />
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
        <button
          className="fvd-btn"
          title="Detect layers & interface sharpness (σ_erf)"
          onClick={run}
          disabled={busy || !activeId}
        >
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
          per-column trace → detrended robust roughness ±CI, spectrum, conformality
        </span>
      </div>
      <div className="fvd-ws-row">
        <label className="k" style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <input
            type="checkbox"
            checked={decurtain}
            onChange={(e) => setDecurtain(e.target.checked)}
          />
          de-curtain (FIB)
        </label>
        <span className="k" style={{ fontSize: 10, opacity: 0.7 }}>
          robust median collapse + FFT notch — suppresses FIB milling streaks
        </span>
      </div>
      <div className="fvd-ws-row">
        <span className="k">≈ foil t</span>
        <input
          value={foilT}
          placeholder="optional"
          style={{ width: 56 }}
          title="Approximate TEM foil thickness (same units as the calibration). Roughness at lateral wavelengths shorter than the foil is projection-smeared — the PSD marks that region and σ_w reads as a lower bound."
          onChange={(e) => setFoilT(e.target.value)}
        />
        <span className="k" style={{ fontSize: 10, opacity: 0.7 }}>
          marks projection-limited wavelengths in the roughness spectrum
        </span>
      </div>

      {result && (
        <AnalysisQualityCard
          value={layerQuality!}
          accepted={qualityAccepted}
          onAccept={() => setQualityAccepted(true)}
        />
      )}
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
      {result && result.layers.length > 0 && (
        <>
          <div className="fvd-ws-section">Layer stack</div>
          <LayerStack r={result} />
        </>
      )}
      {result && result.depth_pos.length > 0 && <DepthPlot r={result} />}

      {result && result.layers.length > 0 && (
        <table className="fvd-ws-table">
          <thead>
            <tr>
              <th>Layer</th>
              <th>Thickness ({result.unit})</th>
              <th title="erf width of the laterally AVERAGED profile — convolves chemical grading with waviness and residual tilt. See σ_chem in the interface detail for the decomposed intrinsic width.">
                σ_erf ({result.unit})
              </th>
              <th title="Geometric interface waviness: detrended, outlier-robust, noise-corrected rms of the per-column trace. A lower bound (projection through the foil).">
                σ_w ({result.unit})
              </th>
              <th title="Pearson r between this layer's two interface traces: ~1 = roughness replicated from below (conformal growth), ~0 = independent.">
                conf r
              </th>
            </tr>
          </thead>
          <tbody>
            {result.layers.map((l) => {
              const top = result.interfaces[l.index];
              const rough = top?.roughness ?? null;
              return (
                <tr key={l.index}>
                  <td>{l.index + 1}</td>
                  <td>
                    {l.thickness.toFixed(2)}
                    {l.thickness_std != null && ` ± ${l.thickness_std.toFixed(2)}`}
                  </td>
                  <td>{top?.sigma_erf == null ? "—" : top.sigma_erf.toFixed(3)}</td>
                  <td>
                    {top?.sigma_w == null ? "—" : top.sigma_w.toFixed(3)}
                    {rough?.sigma_ci && (
                      <span className="dim" style={{ fontSize: 10 }}>
                        {" "}
                        [{rough.sigma_ci[0].toFixed(2)}–{rough.sigma_ci[1].toFixed(2)}]
                      </span>
                    )}
                    {rough != null && rough.quality < 0.9 && (
                      <span title={`only ${(rough.quality * 100).toFixed(0)}% of trace columns usable`}> ⚠</span>
                    )}
                  </td>
                  <td>{l.conformality == null ? "—" : l.conformality.toFixed(2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {result && result.interfaces.some((i) => i.roughness) && (
        <>
          <div className="fvd-ws-row" style={{ flexWrap: "wrap", gap: 4 }}>
            <span className="k">Interface detail</span>
            {result.interfaces.map((i, k) => (
              <button
                key={k}
                className={`fvd-seg-btn${detailIdx === k ? " active" : ""}`}
                title={`Interface ${k + 1} at depth ${i.position.toFixed(1)} px — click for the full roughness report (or click its line on the image)`}
                onClick={() => setDetailIdx(detailIdx === k ? null : k)}
              >
                {k + 1}
              </button>
            ))}
          </div>
          {detailIdx != null && result.interfaces[detailIdx] && (
            <LayersRoughnessDetail
              iface={result.interfaces[detailIdx]}
              index={detailIdx}
              unit={result.unit}
              foilT={Number(foilT) > 0 ? Number(foilT) : null}
            />
          )}
        </>
      )}
      {result && (
        <div className="fvd-ws-row">
          <label className="k" style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <input
              type="checkbox"
              checked={layersEdit}
              disabled={!canUseResult}
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
                  disabled={busy || !canUseResult}
                  onClick={() =>
                    canUseResult && recompute(
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
              disabled={!canUseResult}
              onChange={(e) => setAddPos(e.target.value)}
            />
            <button
              className="fvd-btn"
              title="Add an interface at the entered depth and recompute"
              disabled={busy || !addPos || !canUseResult}
              onClick={() => {
                if (!canUseResult) return;
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
          <button className="fvd-btn" disabled={!canUseResult} onClick={() => exportCsv(result)} title="Export layers + interfaces as CSV">
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
            title="Measure the same interfaces across the selected element maps"
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
