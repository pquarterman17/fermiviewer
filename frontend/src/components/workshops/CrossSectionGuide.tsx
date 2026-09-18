import { useEffect, useState } from "react";

import { useAnalysisRoi } from "../../hooks/useAnalysisRoi";
import { assessGrainQuality, assessLayerQuality } from "../../lib/analysisQuality";
import { buildCrossSectionReport } from "../../lib/crossSectionReport";
import { layersCsvText, profileCsvText } from "../../lib/layersCsv";
import { downloadCsv, downloadJson, exportBaseName } from "../../lib/resultsExport";
import { matchesCrossSectionRegion, useCrossSection } from "../../store/crossSection";
import { useViewer } from "../../store/viewer";
import { grainSourceId } from "../../lib/grainWorkflow";
import AnalysisRegionSelect from "./AnalysisRegionSelect";
import { GrainMetrics } from "./AnalysisQualityCard";
import CrossSectionPerLayer from "./CrossSectionPerLayer";
import LayersWorkshop, { LayerStack } from "./LayersWorkshop";
import { GrainsMode } from "./StructureWorkshop";

const STEPS = ["Region", "Layers", "Grains", "Report"] as const;

export default function CrossSectionGuide() {
  const [step, setStep] = useState(0);
  const [selectedLayers, setSelectedLayers] = useState<number[]>([]);
  const activeId = useViewer((s) => s.activeId);
  const images = useViewer((s) => s.images);
  const setActive = useViewer((s) => s.setActive);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const setStatus = useViewer((s) => s.setStatus);
  const sourceId = activeId ? grainSourceId(activeId, images) : null;
  const source = sourceId ? (images[sourceId] ?? null) : null;
  const region = useAnalysisRoi(sourceId, source?.shape ?? []);
  const latestLayers = useCrossSection((s) => s.layers);
  const latestGrains = useCrossSection((s) => s.grains);
  const latestPerLayer = useCrossSection((s) => s.perLayer);
  const layers = matchesCrossSectionRegion(latestLayers, sourceId, region.roi) ? latestLayers : null;
  const grains = matchesCrossSectionRegion(latestGrains, sourceId, region.roi) ? latestGrains : null;
  const perLayer = matchesCrossSectionRegion(latestPerLayer, sourceId, region.roi)
    && latestPerLayer?.selectedLayerIndices.join(":") === selectedLayers.join(":")
    ? latestPerLayer : null;

  useEffect(() => {
    setSelectedLayers(layers?.result.layers.map((layer) => layer.index) ?? []);
  }, [layers?.result]);

  if (!sourceId || !source || source.kind !== "image") {
    return <div className="fvd-ws-empty">Select a 2-D TEM/STEM image to begin.</div>;
  }

  const go = (next: number) => {
    setActive(sourceId);
    setStep(next);
  };
  const base = exportBaseName(source.name);
  const exportReport = () => {
    const report = buildCrossSectionReport(source, region.label, layers, grains, perLayer);
    const name = `${base}_cross_section.json`;
    downloadJson(name, JSON.stringify(report, null, 2) + "\n");
    setStatus(`cross-section report: exported ${name}`);
  };
  const exportLayersCsv = () => {
    if (!layers) return;
    const name = `${base}_layers.csv`;
    downloadCsv(name, layersCsvText(layers.result));
    setStatus(`cross-section report: exported ${name}`);
  };
  const exportProfileCsv = () => {
    if (!layers) return;
    const name = `${base}_depth_profile.csv`;
    downloadCsv(name, profileCsvText(layers.result));
    setStatus(`cross-section report: exported ${name}`);
  };
  const layerQuality = layers ? assessLayerQuality(layers.result) : null;
  const grainQuality = grains
    ? assessGrainQuality(grains.result, source.shape, grains.minArea, grains.roi)
    : null;
  const reportBlocked = Boolean(
    (layerQuality?.rating === "poor" && !layers?.qualityAccepted) ||
    (grainQuality?.rating === "poor" && !grains?.qualityAccepted),
  );
  // Advisory, NOT a gate. `buildCrossSectionReport` already emits
  // `per_layer_grains: null` plus a limitations line when this step was not
  // run, so blocking export on it enforced a precondition the report format
  // does not have. Worse, `setLayers`/`setGrains` both reset `perLayer`, so
  // nudging one interface silently re-armed the block and an export that
  // worked a minute earlier went dead with no error -- a disabled button
  // swallows the click entirely.
  const perLayerMissing = Boolean(layers && grains && !perLayer);

  return (
    <div className="fvd-ws fvd-cross-guide">
      <div className="fvd-guide-steps" aria-label="Cross-section workflow">
        {STEPS.map((label, index) => (
          <button
            key={label}
            className={`fvd-guide-step${step === index ? " active" : ""}`}
            onClick={() => go(index)}
          >
            <span>{index + 1}</span>{label}
            {index === 1 && layers && <b>✓</b>}
            {index === 2 && grains && <b>✓</b>}
          </button>
        ))}
      </div>

      <div className="fvd-ws-note">
        Source: {source.name} · {source.shape[1]}×{source.shape[0]}
        {source.pixel_size ? ` · ${source.pixel_size} ${source.pixel_unit}/px` : " · uncalibrated"}
      </div>

      {step === 0 && (
        <div className="fvd-guide-pane">
          <div className="fvd-ws-section">Choose the film region</div>
          <p className="fvd-ws-note">
            Exclude vacuum, substrate-only margins, scale bars, and damaged edges.
            The same region is shared with both analyses.
          </p>
          <AnalysisRegionSelect
            choice={region.choice}
            imageId={sourceId}
            roi={region.roi}
            options={region.options}
            disabled={false}
            onChange={region.setChoice}
          />
          <div className="fvd-ws-row">
            <button className="fvd-btn" onClick={() => {
              setActive(sourceId);
              setCaptureMode("roi");
              setStatus("cross-section: drag a film ROI on the source image");
            }}>Draw ROI</button>
            <span className="k">Current: {region.label}</span>
          </div>
          {!source.pixel_size && (
            <div className="fvd-quality review">Calibrate the image before interpreting physical thickness or ASTM grain size.</div>
          )}
        </div>
      )}

      {step === 1 && <LayersWorkshop />}
      {step === 2 && <GrainsMode id={sourceId} />}
      {step === 3 && (
        <div className="fvd-guide-pane">
          <div className="fvd-ws-section">Reviewed cross-section summary</div>
          {!layers && <div className="fvd-ws-note">Run layer detection for this region.</div>}
          {layers && (
            <>
              <div className="fvd-guide-summary">
                <b>Layers</b><span>{layers.result.layers.length}</span>
                <b>Interfaces</b><span>{layers.result.interfaces.length}</span>
                <b>Quality</b><span>{layerQuality?.rating}</span>
              </div>
              {layers.result.layers.length > 0 && <LayerStack r={layers.result} />}
            </>
          )}
          {!grains && <div className="fvd-ws-note">Run grain segmentation for this region.</div>}
          {grains && (
            <>
              <div className="fvd-guide-summary">
                <b>Grain method</b><span>{grains.result.method}</span>
                <b>Quality</b><span>{grainQuality?.rating}</span>
              </div>
              <GrainMetrics r={grains.result} />
            </>
          )}
          {layers && grains && sourceId && (
            <CrossSectionPerLayer
              sourceId={sourceId} roi={region.roi} layers={layers} grains={grains}
              selected={selectedLayers} onSelected={setSelectedLayers}
            />
          )}
          {reportBlocked && (
            <div className="fvd-quality poor">A poor result must be acknowledged in its analysis step before combined export.</div>
          )}
          {perLayerMissing && (
            <div className="fvd-quality review">
              No per-layer grain measurement yet. Exporting now is fine — the report
              records its absence as a limitation rather than omitting it silently.
            </div>
          )}
          <div className="fvd-guide-exports">
            <button
              className="fvd-btn primary"
              disabled={(!layers && !grains) || reportBlocked}
              title={reportBlocked
                ? "Acknowledge the poor result in its analysis step first"
                : (!layers && !grains)
                  ? "Run the layers or grains step first"
                  : "Layers, grains and per-layer grains as one JSON report"}
              onClick={exportReport}
            >
              Export combined JSON report
            </button>
            <button
              className="fvd-btn"
              disabled={!layers || reportBlocked}
              title={layers
                ? "Layer thicknesses and interface roughness as CSV"
                : "Run the layers step first"}
              onClick={exportLayersCsv}
            >
              Export layers CSV
            </button>
            <button
              className="fvd-btn"
              disabled={!layers || reportBlocked}
              title={layers
                ? "The integrated depth profile the interfaces were found in"
                : "Run the layers step first"}
              onClick={exportProfileCsv}
            >
              Export profile CSV
            </button>
          </div>
          <div className="fvd-ws-note">
            Per-layer grains are clipped at reviewed interfaces; shape angles are morphological, not crystallographic.
          </div>
        </div>
      )}

      <div className="fvd-guide-nav">
        <button className="fvd-btn" disabled={step === 0} onClick={() => go(step - 1)}>Back</button>
        <span>{step + 1} of {STEPS.length}</span>
        <button className="fvd-btn primary" disabled={step === STEPS.length - 1} onClick={() => go(step + 1)}>Next</button>
      </div>
    </div>
  );
}
