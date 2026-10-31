// Cross-section / Layers workshop (PLAN_CROSS_SECTION_LAYERS Tier 1 #3):
// auto-orient + measure layer thicknesses and interface sharpness (σ_erf)
// from a cross-sectional EM image. Depth-profile plot marks the detected
// interfaces; the table reports thickness ± σ_erf with CSV export.
//
// The LayerStack band diagram, CSV export and the Single/Compare mode
// toggle live in ./layers/ (repo-health #33 split); this file keeps the
// main workshop component and re-exports LayerStack so no external import
// site changes.

import { useEffect, useState } from "react";

import type { LayersResult } from "../../lib/api";
import {
  layerOverlayCoordinates,
  roiLocalDepths,
  useAnalysisRoi,
  type AnalysisRoi,
} from "../../hooks/useAnalysisRoi";
import { useViewer } from "../../store/viewer";
import { acceptCrossSectionLayers, useCrossSection } from "../../store/crossSection";
import { assessLayerQuality } from "../../lib/analysisQuality";
import { AnalysisQualityCard } from "./AnalysisQualityCard";
import AnalysisRegionSelect from "./AnalysisRegionSelect";
import DepthPlot from "./LayersDepthPlot";
import LayersRoughnessDetail from "./LayersRoughnessDetail";
import LayersMultiCompare from "./LayersMultiCompare";
import { LayerStack, exportCsv } from "./layers/LayerStack";
import { LayersControls } from "./layers/LayersControls";
import { LayersMode } from "./layers/LayersMode";
import { useLayersRuns } from "./layers/useLayersRuns";
import { useLayersStageEdits } from "./layers/useLayersStageEdits";

export { LayerStack } from "./layers/LayerStack";

export default function LayersWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) => (s.activeId ? (s.images[s.activeId] ?? null) : null));
  const setStatus = useViewer((s) => s.setStatus);
  const setLayersOverlay = useViewer((s) => s.setLayersOverlay);
  const layersEdit = useViewer((s) => s.layersEdit);
  const setLayersEdit = useViewer((s) => s.setLayersEdit);
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
  const [mode, setMode] = useState<"single" | "compare">("single");
  const [saveResult, setSaveResult] = useState(false);
  // The tilt the profile is collapsed along. Held here rather than read off
  // the last result because it is an INPUT: `result.tilt_deg` is what the
  // orientation detector measured, which is a different number and must not
  // silently become the correction.
  const [tiltDeg, setTiltDeg] = useState<number | null>(null);
  const layersFocusReq = useViewer((s) => s.layersFocusReq);
  const setLayersFocusReq = useViewer((s) => s.setLayersFocusReq);
  const images = useViewer((s) => s.images);
  const order = useViewer((s) => s.order);
  const [qualityAccepted, setQualityAccepted] = useState(false);
  const analysisRoi = useAnalysisRoi(activeId, meta?.shape ?? []);
  const roiKey = analysisRoi.roi?.join(":") ?? "whole";

  const isImage = meta?.kind === "image";
  const mapIds = order.filter((id) => images[id]?.kind === "image");
  const layerQuality = result
    ? assessLayerQuality(result, Number(nLayers) || 0)
    : null;
  const canUseResult = layerQuality?.rating !== "poor" || qualityAccepted;

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
        r.applied_tilt_deg == null
          ? null
          : { tiltDeg: r.applied_tilt_deg, nDepth: r.depth_pos.length },
      );
      setLayersOverlay({
        imageId,
        axis: r.axis,
        tiltDeg: r.applied_tilt_deg ?? 0,
        ...overlay,
      });
      useCrossSection.getState().setLayers({
        sourceId: imageId,
        regionLabel: analysisRoi.label,
        roi,
        result: r,
        qualityAccepted: false,
      });
    }
    setStatus(
      `Layers: ${r.layers.length} layer(s), ${r.interfaces.length} interface(s)` +
        ` · ${r.axis}-axis · tilt ${r.tilt_deg == null ? "?" : r.tilt_deg.toFixed(1)}°`,
    );
  };

  const { run, recompute, levelImage } = useLayersRuns({
    activeId,
    roi: analysisRoi.roi,
    roiKey,
    result,
    tiltDeg,
    params: { axis, modality, sensitivity, nLayers, waviness, decurtain, saveResult },
    setBusy,
    setStatus,
    applyResult,
  });

  // clear any prior overlay + edit state when the image changes / unmounts
  useEffect(() => {
    setResult(null);
    setLayersOverlay(null);
    setLayersEdit(false);
    setLayersEditReq(null);
    setDetailIdx(null);
    setQualityAccepted(false);
    setBusy(false);
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

  useLayersStageEdits({
    ready: result !== null,
    onPositions: (p) =>
      result && recompute(roiLocalDepths(result.axis, p, analysisRoi.roi)),
    onTilt: (deg) => {
      setTiltDeg(deg);
      run(deg);
    },
  });

  if (!isImage) {
    return (
      <div className="fvd-ws-empty">
        Select a 2-D image (derive an element/score map from a cube first).
      </div>
    );
  }

  if (mode === "compare" && activeId) {
    return (
      <div className="fvd-ws">
        <LayersMode value={mode} onChange={setMode} />
        <AnalysisRegionSelect
          choice={analysisRoi.choice}
          imageId={activeId}
          roi={analysisRoi.roi}
          options={analysisRoi.options}
          disabled={false}
          onChange={analysisRoi.setChoice}
        />
        <LayersMultiCompare
          activeId={activeId}
          mapIds={mapIds}
          images={images}
          roi={analysisRoi.roi}
          regionLabel={analysisRoi.label}
        />
      </div>
    );
  }

  return (
    <div className="fvd-ws">
      <LayersMode value={mode} onChange={setMode} />
      <AnalysisRegionSelect
        choice={analysisRoi.choice}
        imageId={activeId}
        roi={analysisRoi.roi}
        options={analysisRoi.options}
        disabled={busy}
        onChange={analysisRoi.setChoice}
      />
      <LayersControls
        axis={axis}
        onAxisChange={setAxis}
        modality={modality}
        onModalityChange={setModality}
        sensitivity={sensitivity}
        onSensitivityChange={setSensitivity}
        nLayers={nLayers}
        onNLayersChange={setNLayers}
        busy={busy}
        activeId={activeId}
        onRun={() => run()}
        waviness={waviness}
        onWavinessChange={setWaviness}
        decurtain={decurtain}
        onDecurtainChange={setDecurtain}
        foilT={foilT}
        onFoilTChange={setFoilT}
      />

      {result && (
        <AnalysisQualityCard
          value={layerQuality!}
          accepted={qualityAccepted}
          onAccept={() => {
            setQualityAccepted(true);
            acceptCrossSectionLayers();
          }}
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
          <label
            className="fvd-check"
            title="Keep this run, its settings, the layer table and the depth profile it was measured from in Results & Methods"
          >
            <input
              type="checkbox"
              checked={saveResult}
              onChange={(e) => setSaveResult(e.target.checked)}
            />
            Save result
          </label>
        </div>
      )}

    </div>
  );
}
