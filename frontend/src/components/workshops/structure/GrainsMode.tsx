// Grains mode (interactive identification window), split out of
// StructureWorkshop.tsx (repo-health #33). Moved verbatim; only imports now
// point one directory up.

import { useEffect, useState } from "react";

import {
  analyzeGrainsAsync,
  grainsTrainPreview,
  grainsTrainSegment,
  runJob,
  type GrainMethod,
  type GrainPreview,
  type GrainResult,
  type TrainStroke,
} from "../../../lib/api";
import {
  csvBaseName,
  downloadCsv,
  downloadGrainsOverlayPng,
  grainsToCsv,
} from "../../../lib/grainsCsv";
import { buildClassicGrainParams, grainSourceId } from "../../../lib/grainWorkflow";
import { assessGrainQuality } from "../../../lib/analysisQuality";
import { pickSizeValues } from "../../../lib/populationHistogram";
import { useAnalysisRoi } from "../../../hooks/useAnalysisRoi";
import { useScribble } from "../../../store/scribble";
import {
  acceptCrossSectionGrains, matchesCrossSectionRegion, recordCrossSectionGrains, useCrossSection,
} from "../../../store/crossSection";
import { useViewer } from "../../../store/viewer";
import { useResults } from "../../overlays/ResultsWindow";
import PopulationHistogram from "../../analysis/PopulationHistogram";
import AnalysisRegionSelect from "../AnalysisRegionSelect";
import { AnalysisQualityCard, GrainMetrics } from "../AnalysisQualityCard";
import Preview from "../StructurePreview";
import { TrainedGrainControls } from "./TrainedGrainControls";

// method → the one tuning knob it exposes; higher coarseness / merge / K
// is fewer, larger grains. Classic k-means is the ported MATLAB path.
export const GRAIN_METHODS: {
  value: GrainMethod;
  label: string;
  knob: string;
  when: string;
}[] = [
  {
    value: "gradient",
    label: "Gradient — visible boundaries",
    knob: "coarseness",
    when: "Visible grain boundaries in the image. Fast watershed on the gradient.",
  },
  {
    value: "rag",
    label: "Superpixel — diffraction contrast",
    knob: "merge thr",
    when: "Diffraction-contrast grains. Over-segments, then merges similar regions.",
  },
  {
    value: "orientation",
    label: "Orientation — atomic-res",
    knob: "coarseness",
    when: "Atomic-resolution lattices. Segments by local crystal orientation.",
  },
  {
    value: "kmeans",
    label: "Classic k-means",
    knob: "classes",
    when: "Simple intensity classes. The ported MATLAB path.",
  },
  {
    value: "trained",
    label: "Trained — paint examples",
    knob: "",
    when: "Anything the others miss. You teach it by painting a few examples.",
  },
];

export function GrainsMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const images = useViewer((s) => s.images);
  const meta = images[id] ?? null;
  const sourceId = grainSourceId(id, images);
  const sourceMeta = images[sourceId] ?? null;
  const analysisRoi = useAnalysisRoi(sourceId, sourceMeta?.shape ?? []);
  const roiKey = analysisRoi.roi?.join(":") ?? "whole";
  const latestGrains = useCrossSection((s) => s.grains);
  const savedGrains = matchesCrossSectionRegion(latestGrains, sourceId, analysisRoi.roi) ? latestGrains : null;
  const [method, setMethod] = useState<GrainMethod>((savedGrains?.result.method as GrainMethod) ?? "gradient");
  const [k, setK] = useState("3");
  const [coarseness, setCoarseness] = useState("0.05");
  const [mergeThr, setMergeThr] = useState("0.08");
  const [minArea, setMinArea] = useState(String(savedGrains?.minArea ?? 25));
  const [denoise, setDenoise] = useState("0");
  // trained-mode pixel classifier: forest (nonlinear, #8) is the default
  const [classifier, setClassifier] = useState<"softmax" | "forest">("forest");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [labelsId, setLabelsId] = useState<string | null>(savedGrains?.result.labels.id ?? null);
  const [grainResult, setGrainResult] = useState<GrainResult | null>(savedGrains?.result ?? null);
  const [note, setNote] = useState("");
  // optional, non-committing preview of the trained classifier's per-class
  // pixel composition (does not register an image or segment grains)
  const [preview, setPreview] = useState<GrainPreview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [qualityAccepted, setQualityAccepted] = useState(savedGrains?.qualityAccepted ?? false);

  // trained-mode scribble state (paint examples directly on the stage)
  const numClasses = useScribble((s) => s.numClasses);
  const classId = useScribble((s) => s.classId);
  const brush = useScribble((s) => s.brush);
  const boundary = useScribble((s) => s.boundary);
  const nStrokes = useScribble((s) => s.strokes.length);
  const scribbleBegin = useScribble((s) => s.begin);
  const scribbleEnd = useScribble((s) => s.end);

  // Restore only when the original source/ROI changes, not when its result becomes active.
  useEffect(() => {
    const saved = useCrossSection.getState().grains;
    const restored = saved?.sourceId === sourceId && (saved.roi?.join(":") ?? "whole") === roiKey ? saved : null;
    setLabelsId(restored?.result.labels.id ?? null);
    setGrainResult(restored?.result ?? null);
    setMethod((restored?.result.method as GrainMethod) ?? "gradient");
    setMinArea(String(restored?.minArea ?? 25));
    setNote("");
    setPreview(null);
    setQualityAccepted(restored?.qualityAccepted ?? false);
  }, [sourceId, roiKey]);

  // Adopt a stage merge/split's new label map — same source/ROI, so restore won't.
  useEffect(() => {
    if (!latestGrains || latestGrains.result.labels.id === labelsId) return;
    if (!matchesCrossSectionRegion(latestGrains, sourceId, analysisRoi.roi)) return;
    setLabelsId(latestGrains.result.labels.id);
    setGrainResult(latestGrains.result);
    setQualityAccepted(latestGrains.qualityAccepted);
  }, [latestGrains, labelsId, sourceId, analysisRoi.roi]);

  // a fresh Clear (or a new image) wipes the strokes → drop the stale preview
  useEffect(() => {
    if (nStrokes === 0) setPreview(null);
  }, [nStrokes]);

  // open/close the stage paint overlay as the Trained method is selected.
  // Never arm paint on a grain-label map (e.g. right after training swaps to
  // the result) — that map drives the merge/split editor instead.
  const sourceIsGrainMap = Boolean(meta?.meta?.["grain_labels"]);
  useEffect(() => {
    if (method !== "trained" || sourceIsGrainMap) return;
    scribbleBegin(sourceId);
    return () => scribbleEnd();
  }, [method, sourceId, sourceIsGrainMap, scribbleBegin, scribbleEnd]);

  const knob = GRAIN_METHODS.find((m) => m.value === method)!.knob;
  const knobValue =
    method === "kmeans" ? k : method === "rag" ? mergeThr : coarseness;
  const setKnob =
    method === "kmeans" ? setK : method === "rag" ? setMergeThr : setCoarseness;
  const grainQuality = grainResult ? assessGrainQuality(
    grainResult,
    sourceMeta?.shape ?? [],
    Number(minArea) || 25,
    analysisRoi.roi,
  ) : null;
  const canUseResult = grainQuality?.rating !== "poor" || qualityAccepted;

  // Classify pixels without creating connected grain labels, then expose the
  // spatial classes and confidence so training errors are visible.
  const previewRun = () => {
    const { strokes, boundary: bnd } = useScribble.getState();
    if (new Set(strokes.map((s) => s.classId)).size < 2) {
      setStatus("trained grains: paint at least 2 different classes");
      return;
    }
    setPreviewBusy(true);
    const payload: TrainStroke[] = strokes.map((s) => ({
      class_id: s.classId,
      radius: s.radius,
      points: s.points,
    }));
    const reqId = sourceId;
    grainsTrainPreview(sourceId, payload, {
      roi: analysisRoi.roi,
      boundaryClass: bnd,
      classifier,
    })
      .then((r) => {
        // ignore a response that arrives after the user switched images
        const state = useViewer.getState();
        const active = state.activeId;
        if (!active || grainSourceId(active, state.images) !== reqId) return;
        const oldPreview = preview;
        if (oldPreview) {
          state.closeImage(oldPreview.class_map.id).catch(() => {});
          state.closeImage(oldPreview.confidence_map.id).catch(() => {});
        }
        state.ingestDerived([r.class_map, r.confidence_map]);
        state.setDisplay(r.class_map.id, { cmap: "label" }, { silent: true });
        state.setDisplay(
          r.confidence_map.id,
          { cmap: "viridis" },
          { silent: true },
        );
        state.setActive(r.class_map.id);
        setPreview(r);
        const phases = r.classes.filter((c) => !c.is_boundary).length;
        setStatus(
          `trained grains: preview — ${phases} phase(s), ${Math.round(r.mean_confidence * 100)}% mean confidence`,
        );
      })
      .catch((e: Error) => setStatus(`trained grains preview: ${e.message}`))
      .finally(() => setPreviewBusy(false));
  };

  const trainRun = () => {
    const { strokes, boundary: bnd } = useScribble.getState();
    if (new Set(strokes.map((s) => s.classId)).size < 2) {
      setStatus("trained grains: paint at least 2 different classes");
      return;
    }
    setBusy(true);
    setProgress("training…");
    const payload: TrainStroke[] = strokes.map((s) => ({
      class_id: s.classId,
      radius: s.radius,
      points: s.points,
    }));
    grainsTrainSegment(sourceId, payload, {
      roi: analysisRoi.roi,
      minArea: Number(minArea) || 25,
      boundaryClass: bnd,
      classifier,
    })
      .then((r) => {
        const s = useViewer.getState();
        s.ingestDerived([r.labels]);
        s.setActive(r.labels.id);
        setLabelsId(r.labels.id);
        setGrainResult(r);
        setQualityAccepted(false);
        recordCrossSectionGrains(sourceId, analysisRoi.label, analysisRoi.roi, Number(minArea) || 25, r);
        setStatus(`trained grains: ${r.n_grains} grains`);
        setNote("click a grain then another to merge · right-click to split");
        useResults.getState().show({
          title: `Grains (${r.n_grains}) · trained`,
          columns: ["#", "area (px)", "perim (px)", "ecc."],
          rows: r.areas_px.map((a, i) => [
            i + 1,
            Math.round(a),
            Math.round(r.perimeters_px[i] ?? 0),
            (r.eccentricity[i] ?? 0).toFixed(2),
          ]),
        });
      })
      .catch((e: Error) => setStatus(`trained grains: ${e.message}`))
      .finally(() => {
        setBusy(false);
        setProgress("");
      });
  };

  const run = () => {
    setBusy(true);
    setProgress("starting…");
    const params = buildClassicGrainParams(
      method as Exclude<GrainMethod, "trained">,
      analysisRoi.roi,
      knobValue,
      minArea,
      denoise,
    );
    runJob<GrainResult>(
      () => analyzeGrainsAsync(sourceId, params),
      (f, msg) => setProgress(`${Math.round(f * 100)}% ${msg}`),
    )
      .then((r) => {
        ingestDerived([r.labels]);
        setLabelsId(r.labels.id);
        setGrainResult(r);
        setQualityAccepted(false);
        recordCrossSectionGrains(sourceId, analysisRoi.label, analysisRoi.roi, Number(minArea) || 25, r);
        // numbers now shown as metric tiles; keep the status line as the terse
        // one-line summary
        const bits = [
          `${r.n_grains} grains`,
          `mean ⌀ ${r.mean_diameter_px.toFixed(1)} px`,
        ];
        if (r.astm_grain_size != null)
          bits.push(`ASTM G ${r.astm_grain_size.toFixed(1)}`);
        bits.push(`${r.n_triple_junctions} junctions`);
        setStatus(`grains: ${bits.join(" · ")}`);
        setNote("");
        useResults.getState().show({
          title: `Grains (${r.n_grains}) · ${r.method}`,
          columns: ["#", "area (px)", "perim (px)", "ecc."],
          rows: r.areas_px.map((a, i) => [
            i + 1,
            Math.round(a),
            Math.round(r.perimeters_px[i] ?? 0),
            (r.eccentricity[i] ?? 0).toFixed(2),
          ]),
        });
      })
      .catch((e: Error) => setStatus(`grains: ${e.message}`))
      .finally(() => {
        setBusy(false);
        setProgress("");
      });
  };

  return (
    <>
      {labelsId ? (
        <Preview id={labelsId} markers={[]} color="var(--capture)" />
      ) : (
        <Preview id={sourceId} markers={[]} color="var(--capture)" />
      )}
      <div className="fvd-ws-note" title={sourceMeta?.name ?? sourceId}>
        Source image: {sourceMeta?.name ?? sourceId}
      </div>
      <AnalysisRegionSelect
        choice={analysisRoi.choice}
        options={analysisRoi.options}
        disabled={busy || previewBusy}
        onChange={analysisRoi.setChoice}
      />
      {analysisRoi.roi && method === "trained" && (
        <div className="fvd-ws-note">Only paint classes inside the selected ROI.</div>
      )}
      <div className="fvd-ws-row">
        <span className="k">method</span>
        <select
          aria-label="Grain method"
          value={method}
          style={{ flex: 1 }}
          onChange={(e) => setMethod(e.target.value as GrainMethod)}
        >
          {GRAIN_METHODS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </div>
      <div className="fvd-ws-note">
        {GRAIN_METHODS.find((m) => m.value === method)!.when}
      </div>
      {method === "trained" ? (
        <TrainedGrainControls
          numClasses={numClasses}
          classId={classId}
          brush={brush}
          boundary={boundary}
          nStrokes={nStrokes}
          minArea={minArea}
          setMinArea={setMinArea}
          classifier={classifier}
          setClassifier={setClassifier}
          busy={busy}
          progress={progress}
          onRun={trainRun}
          onPreview={previewRun}
          previewBusy={previewBusy}
          preview={preview}
          activeId={id}
          sourceId={sourceId}
          showPreview={(previewId) => useViewer.getState().setActive(previewId)}
        />
      ) : (
        <div className="fvd-ws-row">
          <span className="k">{knob}</span>
          <input
            value={knobValue}
            style={{ width: 44 }}
            onChange={(e) => setKnob(e.target.value)}
          />
          {method !== "kmeans" && (
            <>
              <span
                className="k"
                title="Gaussian denoise σ (px) before segmenting — raise to tame noisy images (0 = off)"
              >
                denoise
              </span>
              <input
                value={denoise}
                style={{ width: 36 }}
                title="Gaussian denoise σ (px); 0 = off"
                onChange={(e) => setDenoise(e.target.value)}
              />
            </>
          )}
          <button
            className="fvd-btn primary"
            onClick={run}
            disabled={busy}
            title="Segment grains with the selected method"
          >
            {busy ? progress || "Segmenting…" : "Identify grains"}
          </button>
        </div>
      )}
      {grainResult && <GrainMetrics r={grainResult} />}
      {grainResult && grainResult.equiv_diameter_px.length > 0 && (
        <PopulationHistogram
          {...pickSizeValues(
            grainResult.equiv_diameter_px,
            grainResult.diameter_calibrated,
            grainResult.unit,
          )}
          title="Grain size distribution"
          filename="grain_size_distribution.png"
        />
      )}
      {grainQuality && (
        <AnalysisQualityCard
          value={grainQuality}
          accepted={qualityAccepted}
          onAccept={() => {
            setQualityAccepted(true);
            acceptCrossSectionGrains();
          }}
        />
      )}
      {note && <div className="fvd-ws-note">{note}</div>}
      {grainResult && labelsId && (
        <div className="fvd-ws-row">
          <button
            className="fvd-btn"
            disabled={!canUseResult}
            onClick={() => {
              const base = csvBaseName(sourceMeta?.name);
              downloadCsv(
                `${base}_grains.csv`,
                grainsToCsv(grainResult, {
                  imageName: sourceMeta?.name ?? sourceId,
                  method: grainResult.method,
                }),
              );
              setStatus(`grains: exported ${grainResult.n_grains} rows`);
            }}
            title="Download grain measurements as CSV"
          >
            CSV
          </button>
          <button
            className="fvd-btn"
            disabled={!canUseResult}
            onClick={() => {
              const base = csvBaseName(sourceMeta?.name);
              downloadGrainsOverlayPng(
                sourceId,
                labelsId,
                `${base}_grains_overlay.png`,
                0.6,
                (msg) => setStatus(`grains PNG: ${msg}`),
              );
            }}
            title="Download the grain-boundary overlay as PNG"
          >
            Overlay PNG
          </button>
        </div>
      )}
    </>
  );
}
