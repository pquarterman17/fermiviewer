// Structure workshop (plan #28 tail): first dedicated UI for the five
// structure endpoints — atom columns (overlay + lattice vectors),
// template match (ROI-as-template, match overlay), CTF (fit plot),
// lattice spacing (two clicks on an FFT) and tile stitching.

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";
import { useShallow } from "zustand/react/shallow";

import {
  analyzeCtf,
  analyzeGpa,
  analyzeGrainsAsync,
  analyzeLattice,
  analyzeParticles,
  analyzeStitch,
  analyzeTemplate,
  fetchData16,
  grainsTrainPreview,
  grainsTrainSegment,
  imageFft,
  renderUrl,
  runJob,
  type CtfResult,
  type GrainMethod,
  type GrainPreviewClass,
  type GrainResult,
  type Raster16,
  type TrainStroke,
} from "../../lib/api";
import {
  csvBaseName,
  downloadCsv,
  downloadGrainsOverlayPng,
  grainsToCsv,
} from "../../lib/grainsCsv";
import { buildClassicGrainParams, grainSourceId } from "../../lib/grainWorkflow";
import { assessGrainQuality } from "../../lib/analysisQuality";
import { useAnalysisRoi } from "../../hooks/useAnalysisRoi";
import AtomColumnPanel from "./AtomColumnPanel";
import { SCRIBBLE_COLORS, useScribble } from "../../store/scribble";
import {
  acceptCrossSectionGrains, matchesCrossSectionRegion, recordCrossSectionGrains, useCrossSection,
} from "../../store/crossSection";
import { useViewer, type Measure } from "../../store/viewer";
import {
  STRUCTURE_MODES,
  STRUCTURE_MODE_DESCRIPTIONS,
  useWorkshop,
} from "../../store/workshop";
import { useResults } from "../overlays/ResultsWindow";
import AnalysisRegionSelect from "./AnalysisRegionSelect";
import { AnalysisQualityCard, GrainMetrics } from "./AnalysisQualityCard";

const VIEW_W = 300;

const NO_MEASURES: Measure[] = [];

export default function StructureWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const mode = useWorkshop((s) => s.structureMode);
  const setMode = useWorkshop((s) => s.setStructureMode);

  const isImage = meta?.kind === "image";

  return (
    <div className="fvd-ws">
      <div className="fvd-seg">
        {STRUCTURE_MODES.map((m) => (
          <button
            key={m}
            className={`fvd-seg-btn${mode === m ? " active" : ""}`}
            onClick={() => setMode(m)}
            title={STRUCTURE_MODE_DESCRIPTIONS[m]}
          >
            {m}
          </button>
        ))}
      </div>
      {!isImage && mode !== "Stitch" ? (
        <div className="fvd-ws-empty">Select a 2D image.</div>
      ) : (
        <>
          {mode === "Atoms" && activeId && <AtomsMode id={activeId} />}
          {mode === "Particles" && activeId && <ParticlesMode id={activeId} />}
          {mode === "Grains" && activeId && <GrainsMode id={activeId} />}
          {mode === "Template" && activeId && <TemplateMode id={activeId} />}
          {mode === "GPA" && activeId && <GpaMode id={activeId} />}
          {mode === "CTF" && activeId && <CtfMode id={activeId} />}
          {mode === "Lattice" && activeId && <LatticeMode id={activeId} />}
          {mode === "Stitch" && <StitchMode />}
        </>
      )}
    </div>
  );
}

// ── shared preview with marker overlay ──────────────────────────────

function Preview({
  id,
  markers,
  color,
  onClick,
}: {
  id: string;
  markers: { x: number; y: number }[]; // 1-based image px
  color: string;
  onClick?: (rowCol: [number, number]) => void;
}) {
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  const scale = nat ? VIEW_W / nat.w : 0;
  const viewH = nat ? nat.h * scale : VIEW_W;
  return (
    <div
      className="fvd-ws-pattern"
      style={{
        width: VIEW_W,
        height: viewH,
        cursor: onClick ? "crosshair" : undefined,
      }}
      onClick={(e) => {
        if (!onClick || !nat) return;
        const r = e.currentTarget.getBoundingClientRect();
        onClick([
          (e.clientY - r.top) / scale + 0.5,
          (e.clientX - r.left) / scale + 0.5,
        ]);
      }}
    >
      <img
        src={renderUrl(id)}
        alt=""
        width={VIEW_W}
        draggable={false}
        onLoad={(e) =>
          setNat({
            w: e.currentTarget.naturalWidth,
            h: e.currentTarget.naturalHeight,
          })
        }
      />
      {nat && (
        <svg width={VIEW_W} height={viewH} pointerEvents="none">
          {markers.map((m, i) => (
            <circle
              key={i}
              cx={(m.x - 0.5) * scale}
              cy={(m.y - 0.5) * scale}
              r={3}
              fill="none"
              stroke={color}
              strokeWidth={1.2}
            />
          ))}
        </svg>
      )}
    </div>
  );
}

// ── Atoms — delegated to AtomColumnPanel ────────────────────────────

function AtomsMode({ id }: { id: string }) {
  return <AtomColumnPanel id={id} />;
}

// ── Particles (live threshold preview) ──────────────────────────────

function ParticlesMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const [thresh, setThresh] = useState(0.5); // normalized vs raster range
  const [polarity, setPolarity] = useState<"bright" | "dark">("bright");
  const [minArea, setMinArea] = useState("5");
  const [busy, setBusy] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rasterRef = useRef<Raster16 | null>(null);
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);

  // fetch the raw raster once per image
  useEffect(() => {
    rasterRef.current = null;
    setDims(null);
    let stale = false;
    fetchData16(id)
      .then((r) => {
        if (stale) return;
        rasterRef.current = r;
        setDims({ w: r.w, h: r.h });
      })
      .catch((e: Error) => setStatus(`particles: ${e.message}`));
    return () => {
      stale = true;
    };
  }, [id, setStatus]);

  // live preview: grayscale base + tinted mask at the threshold
  useEffect(() => {
    const r = rasterRef.current;
    const cv = canvasRef.current;
    if (!r || !cv || !dims) return;
    cv.width = r.w;
    cv.height = r.h;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const img = ctx.createImageData(r.w, r.h);
    const cut = thresh * 65535;
    for (let i = 0; i < r.w * r.h; i++) {
      const v = r.data[i];
      const g = v >> 8;
      const hit = polarity === "bright" ? v >= cut : v <= cut;
      const o = i * 4;
      img.data[o] = hit ? 244 : g;
      img.data[o + 1] = hit ? 63 : g;
      img.data[o + 2] = hit ? 94 : g;
      img.data[o + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  }, [thresh, polarity, dims]);

  const count = () => {
    const r = rasterRef.current;
    if (!r) return;
    setBusy(true);
    // slider is normalized — the endpoint wants real intensity
    const realThr = r.vmin + thresh * (r.vmax - r.vmin);
    analyzeParticles(id, {
      threshold: realThr,
      polarity,
      minArea: Number(minArea) || 1,
    })
      .then((res) => {
        const s = useViewer.getState();
        s.ingestDerived([res.labels]);
        s.setStatus(`particles: ${res.n_particles} found`);
        useResults.getState().show({
          title: `Particles (${res.n_particles}) — ${res.unit}`,
          columns: ["id", "area", "equiv ⌀", "mean I", "cx", "cy"],
          rows: res.particles.map((p) => [
            p.id,
            p.area,
            Number(p.equiv_diameter.toPrecision(4)),
            Number(p.mean_intensity.toPrecision(4)),
            Number(p.centroid[0].toFixed(1)),
            Number(p.centroid[1].toFixed(1)),
          ]),
        });
      })
      .catch((e: Error) => setStatus(`particles: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const viewH = dims ? (dims.h / dims.w) * VIEW_W : VIEW_W;
  return (
    <>
      <div className="fvd-ws-pattern" style={{ width: VIEW_W, height: viewH }}>
        <canvas
          ref={canvasRef}
          style={{
            width: VIEW_W,
            height: viewH,
            imageRendering: "pixelated",
          }}
        />
      </div>
      <div className="fvd-ws-row">
        <span className="k">thr</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.005}
          value={thresh}
          style={{ flex: 1 }}
          onChange={(e) => setThresh(Number(e.target.value))}
        />
        <span className="k">{thresh.toFixed(3)}</span>
      </div>
      <div className="fvd-ws-row">
        <div className="fvd-seg">
          {(["bright", "dark"] as const).map((p) => (
            <button
              key={p}
              className={`fvd-seg-btn${polarity === p ? " active" : ""}`}
              onClick={() => setPolarity(p)}
              title={`Detect ${p} particles on a ${p === "bright" ? "dark" : "bright"} background`}
            >
              {p}
            </button>
          ))}
        </div>
        <span className="k">min px</span>
        <input
          value={minArea}
          style={{ width: 40 }}
          onChange={(e) => setMinArea(e.target.value)}
        />
        <button
          className="fvd-btn primary"
          onClick={count}
          disabled={busy}
          title="Count particles above the threshold and list area/centroid"
        >
          {busy ? "Counting…" : "Count"}
        </button>
      </div>
    </>
  );
}

// ── Grains (interactive identification window) ───────────────────────

// method → the one tuning knob it exposes; higher coarseness / merge / K
// is fewer, larger grains. Classic k-means is the ported MATLAB path.
const GRAIN_METHODS: {
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

// Distinct non-boundary classes that have at least one painted stroke — the
// pixel classifier needs ≥2 of these to train. A class flagged ∅ (boundary/
// background) is excluded from the count even if painted, since it labels the
// boundary rather than a grain phase.
export function paintedReadyCount(
  strokes: { classId: number }[],
  boundary: number[],
): number {
  const painted = new Set(strokes.map((s) => s.classId));
  return Array.from(painted).filter((c) => !boundary.includes(c)).length;
}

// Color-keyed legend of the trained classifier's per-class pixel composition
// (the optional preview). Boundary (∅) classes show a dashed hollow chip.
export function TrainedPreviewLegend({
  classes,
}: {
  classes: GrainPreviewClass[];
}) {
  return (
    <div className="fvd-legend">
      {classes.map((c) => {
        const col = SCRIBBLE_COLORS[(c.class_id - 1) % SCRIBBLE_COLORS.length];
        return (
          <div key={c.class_id} className="fvd-legend-item">
            <span
              className="fvd-legend-chip"
              style={{
                background: c.is_boundary ? "transparent" : col,
                border: c.is_boundary ? "1px dashed var(--text-faint)" : "none",
              }}
            />
            <span className="fvd-legend-label">
              {c.is_boundary ? "∅ " : ""}Class {c.class_id}
            </span>
            <span className="fvd-legend-val">
              {Math.round(c.fraction * 100)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}

// Trained-mode controls: pick a class, set the brush, paint examples on the
// stage, then train+segment. A class can be flagged as boundary/background
// (∅) so its pixels are excluded from grains.
function TrainedGrainControls({
  numClasses,
  classId,
  brush,
  boundary,
  nStrokes,
  minArea,
  setMinArea,
  classifier,
  setClassifier,
  busy,
  progress,
  onRun,
  onPreview,
  previewBusy,
  previewClasses,
}: {
  numClasses: number;
  classId: number;
  brush: number;
  boundary: number[];
  nStrokes: number;
  minArea: string;
  setMinArea: (v: string) => void;
  classifier: "softmax" | "forest";
  setClassifier: (v: "softmax" | "forest") => void;
  busy: boolean;
  progress: string;
  onRun: () => void;
  onPreview: () => void;
  previewBusy: boolean;
  previewClasses: GrainPreviewClass[] | null;
}) {
  const setClass = useScribble((s) => s.setClass);
  const setNumClasses = useScribble((s) => s.setNumClasses);
  const setBrush = useScribble((s) => s.setBrush);
  const toggleBoundary = useScribble((s) => s.toggleBoundary);
  const clear = useScribble((s) => s.clear);
  // live painted-state (the design's ✓/○ chips): which classes have at least
  // one stroke, and how many non-boundary classes are painted (≥2 to train).
  // Read the stroke array by reference — no fresh-array selector, so no
  // re-render churn.
  const strokes = useScribble((s) => s.strokes);
  const painted = new Set(strokes.map((s) => s.classId));
  const readyCount = paintedReadyCount(strokes, boundary);

  return (
    <>
      <div className="fvd-ws-row">
        <span className="k">classes</span>
        <div style={{ display: "flex", gap: 4, flex: 1, flexWrap: "wrap" }}>
          {Array.from({ length: numClasses }, (_, i) => i + 1).map((c) => {
            const col = SCRIBBLE_COLORS[(c - 1) % SCRIBBLE_COLORS.length];
            const isBnd = boundary.includes(c);
            return (
              <button
                key={c}
                className="fvd-btn"
                title={
                  (isBnd ? "boundary/background class" : `class ${c}`) +
                  (painted.has(c) ? " · painted" : " · not painted yet")
                }
                onClick={() => setClass(c)}
                style={{
                  minWidth: 26,
                  padding: "2px 6px",
                  background: col,
                  color: "#111",
                  outline: classId === c ? "2px solid #fff" : "none",
                  opacity: isBnd ? 0.5 : 1,
                }}
              >
                {isBnd ? "∅" : c}
                {painted.has(c) && (
                  <span style={{ marginLeft: 3, fontSize: 9 }}>✓</span>
                )}
              </button>
            );
          })}
        </div>
        <button
          className="fvd-btn"
          title="fewer classes"
          onClick={() => setNumClasses(numClasses - 1)}
        >
          −
        </button>
        <button
          className="fvd-btn"
          title="more classes"
          onClick={() => setNumClasses(numClasses + 1)}
        >
          +
        </button>
      </div>
      <div className="fvd-ws-row">
        <span className="k">brush</span>
        <input
          type="range"
          min={1}
          max={40}
          value={brush}
          style={{ flex: 1 }}
          onChange={(e) => setBrush(Number(e.target.value))}
        />
        <span style={{ width: 28, textAlign: "right" }}>{brush}px</span>
        <button
          className="fvd-btn"
          title="mark the current class as boundary/background"
          onClick={() => toggleBoundary(classId)}
          style={{
            outline: boundary.includes(classId) ? "2px solid #fff" : "none",
          }}
        >
          ∅
        </button>
      </div>
      <div className="fvd-ws-row">
        <span className="k">model</span>
        <select
          value={classifier}
          style={{ flex: 1 }}
          title="Forest learns nonlinear texture boundaries; softmax is a faster linear model"
          onChange={(e) =>
            setClassifier(e.target.value as "softmax" | "forest")
          }
        >
          <option value="forest">Random forest — nonlinear</option>
          <option value="softmax">Softmax — linear, fast</option>
        </select>
      </div>
      <div className="fvd-ws-row">
        <span className="k">min area</span>
        <input
          value={minArea}
          style={{ width: 44 }}
          onChange={(e) => setMinArea(e.target.value)}
        />
        <span style={{ flex: 1 }} />
        <button
          className="fvd-btn"
          style={{ flex: "0 0 auto", padding: "4px 10px" }}
          onClick={clear}
          disabled={nStrokes === 0}
          title="Clear all painted training strokes"
        >
          Clear
        </button>
      </div>
      <div className="fvd-ws-row">
        <button
          className="fvd-btn"
          title="Preview the pixel classification (per-class %) without committing to grains"
          onClick={onPreview}
          disabled={previewBusy || busy || nStrokes === 0}
        >
          {previewBusy ? "Previewing…" : "Preview"}
        </button>
        <button
          className="fvd-btn primary"
          onClick={onRun}
          disabled={busy || previewBusy || nStrokes === 0}
          title="Train the classifier on your strokes, then segment grains"
        >
          {busy ? progress || "Training…" : "Train & segment"}
        </button>
      </div>
      {previewClasses && (
        <>
          <div className="fvd-ws-note">
            pixel classification preview — check the split, then train &amp;
            segment
          </div>
          <TrainedPreviewLegend classes={previewClasses} />
        </>
      )}
      <div
        className="fvd-ws-note"
        style={{ color: readyCount >= 2 ? "var(--capture)" : undefined }}
      >
        {readyCount >= 2
          ? `${readyCount} classes painted · ready to train & segment`
          : `paint ${2 - readyCount} more class${
              2 - readyCount === 1 ? "" : "es"
            } to train`}
      </div>
      <div className="fvd-ws-note">
        Paint a few strokes of each class on the image, then train. ∅ marks a
        class as boundary/background (excluded from grains).
      </div>
    </>
  );
}

export { grainSourceId } from "../../lib/grainWorkflow";
export function GrainsMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const images = useViewer((s) => s.images);
  const meta = images[id] ?? null;
  const sourceId = grainSourceId(id, images);
  const sourceMeta = images[sourceId] ?? null;
  const analysisRoi = useAnalysisRoi(sourceId, sourceMeta?.shape ?? []);
  const roiKey = analysisRoi.roi?.join(":") ?? "whole";
  const latestGrains = useCrossSection.getState().grains;
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
  const [previewClasses, setPreviewClasses] = useState<
    GrainPreviewClass[] | null
  >(null);
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
    setPreviewClasses(null);
    setQualityAccepted(restored?.qualityAccepted ?? false);
  }, [sourceId, roiKey]);

  // a fresh Clear (or a new image) wipes the strokes → drop the stale preview
  useEffect(() => {
    if (nStrokes === 0) setPreviewClasses(null);
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

  // optional preview: classify pixels from the current strokes and show the
  // per-class composition, committing nothing (no image, no grain labels)
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
        setPreviewClasses(r.classes);
        const phases = r.classes.filter((c) => !c.is_boundary).length;
        setStatus(`trained grains: preview — ${phases} phase(s) classified`);
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
          previewClasses={previewClasses}
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

// ── Template match ───────────────────────────────────────────────────

function TemplateMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const meta = useViewer((s) => s.images[id] ?? null);
  // useShallow: the .filter() returns a fresh array each call; without a
  // shallow compare this selector re-renders every store tick (the
  // documented zustand black-screen class).
  const rois = useViewer(
    useShallow((s) =>
      (s.measures[id] ?? NO_MEASURES).filter((m) => m.kind === "roi"),
    ),
  );
  const [thresh, setThresh] = useState("0.7");
  const [matches, setMatches] = useState<[number, number][]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setMatches([]);
    setNote("");
  }, [id]);

  const run = () => {
    if (!meta || rois.length === 0) return;
    const roi = rois[rois.length - 1];
    const [h, w] = meta.shape;
    const r0 = Math.max(
      1,
      Math.round(Math.min(roi.pts[0].y, roi.pts[1].y) * h + 0.5),
    );
    const c0 = Math.max(
      1,
      Math.round(Math.min(roi.pts[0].x, roi.pts[1].x) * w + 0.5),
    );
    const th = Math.max(
      1,
      Math.round(Math.abs(roi.pts[1].y - roi.pts[0].y) * h),
    );
    const tw = Math.max(
      1,
      Math.round(Math.abs(roi.pts[1].x - roi.pts[0].x) * w),
    );
    setBusy(true);
    analyzeTemplate(id, [r0, c0, th, tw], Number(thresh) || 0.7)
      .then((r) => {
        setMatches(r.locations);
        const top = r.scores.length ? Math.max(...r.scores) : 0;
        setNote(`${r.n_matches} matches · top score ${top.toFixed(3)}`);
      })
      .catch((e: Error) => setStatus(`template: ${e.message}`))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <Preview
        id={id}
        markers={matches.map(([r, c]) => ({ x: c, y: r }))}
        color="#f59e0b"
      />
      <div className="fvd-ws-row">
        <span className="k">thr</span>
        <input
          value={thresh}
          style={{ width: 44 }}
          onChange={(e) => setThresh(e.target.value)}
        />
        <button
          className="fvd-btn primary"
          onClick={run}
          disabled={busy || rois.length === 0}
          title={
            rois.length
              ? "Template-match the latest ROI motif across the image"
              : "draw an ROI around the motif first (R)"
          }
        >
          {busy ? "Matching…" : "Match ROI template"}
        </button>
      </div>
      <div className="fvd-ws-note">
        {rois.length === 0
          ? "Draw an ROI (R) around the motif to use as template."
          : note || `template = latest of ${rois.length} ROI(s)`}
      </div>
    </>
  );
}

// ── GPA (2-click g-vector picks on the FFT) ──────────────────────────

function GpaMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const meta = useViewer((s) => s.images[id] ?? null);
  const [fftId, setFftId] = useState<string | null>(null);
  const [spots, setSpots] = useState<[number, number][]>([]);
  const [mean, setMean] = useState<Record<string, number> | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setFftId(null);
    setSpots([]);
    setMean(null);
    let stale = false;
    imageFft(id)
      .then((m) => {
        if (!stale) setFftId(m.id);
      })
      .catch((e: Error) => setStatus(`gpa: ${e.message}`));
    return () => {
      stale = true;
    };
  }, [id, setStatus]);

  const onClick = (rc: [number, number]) => {
    const next = [...spots, rc].slice(-2) as [number, number][];
    setSpots(next);
    setMean(null);
    if (next.length === 2 && meta) {
      // FFT centre at floor(N/2)+1 (1-based, the pinned convention)
      const cr = Math.floor(meta.shape[0] / 2) + 1;
      const cc = Math.floor(meta.shape[1] / 2) + 1;
      const g = (s: [number, number]): [number, number] => [
        s[1] - cc, // gx (cols)
        s[0] - cr, // gy (rows)
      ];
      setBusy(true);
      analyzeGpa(id, g(next[0]), g(next[1]))
        .then((r) => {
          ingestDerived(r.maps);
          setMean(r.mean);
          setStatus(`GPA: εxx, εyy, εxy, ω maps registered`);
        })
        .catch((e: Error) => setStatus(`gpa: ${e.message}`))
        .finally(() => setBusy(false));
    }
  };

  return (
    <>
      {fftId && (
        <Preview
          id={fftId}
          markers={spots.map(([r, c]) => ({ x: c, y: r }))}
          color="var(--capture)"
          onClick={onClick}
        />
      )}
      <div className="fvd-ws-note">
        {busy
          ? "Computing strain maps…"
          : spots.length < 2
            ? `Click ${2 - spots.length} non-collinear g spot${
                spots.length === 1 ? "" : "s"
              } on the FFT.`
            : "Click again to restart."}
      </div>
      {mean && (
        <div className="fvd-ws-note">
          ε̄xx {fmtMean(mean["exx"])} · ε̄yy {fmtMean(mean["eyy"])} · ε̄xy{" "}
          {fmtMean(mean["exy"])} · ω̄ {fmtMean(mean["rotation"])} rad
        </div>
      )}
    </>
  );
}

function fmtMean(v: number | undefined): string {
  return v === undefined ? "—" : v.toExponential(2);
}

// ── CTF ──────────────────────────────────────────────────────────────

function CtfMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const [kv, setKv] = useState("200");
  const [cs, setCs] = useState("1.2");
  const [pxA, setPxA] = useState("1.0");
  const [res, setRes] = useState<CtfResult | null>(null);
  const [busy, setBusy] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => setRes(null), [id]);

  useEffect(() => {
    const el = host.current;
    plotRef.current?.destroy();
    plotRef.current = null;
    if (!el || !res) return;
    const accent =
      getComputedStyle(document.documentElement)
        .getPropertyValue("--accent")
        .trim() || "#a78bfa";
    plotRef.current = new uPlot(
      {
        width: el.clientWidth,
        height: 160,
        scales: { x: { time: false } }, // x is spatial frequency, not time
        series: [
          {},
          { label: "power", stroke: "#8888aa", width: 1 },
          { label: "CTF² fit", stroke: accent, width: 1.5 },
        ],
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
        ],
        legend: { show: false },
        cursor: { y: false },
      },
      [res.radial_freq, res.radial_power, res.ctf_fit],
      el,
    );
    return () => {
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [res]);

  const run = () => {
    setBusy(true);
    analyzeCtf(id, {
      voltageKv: Number(kv) || 200,
      csMm: Number(cs) || 1.2,
      pixelSizeA: Number(pxA) || 1,
    })
      .then(setRes)
      .catch((e: Error) => setStatus(`ctf: ${e.message}`))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <div className="fvd-ws-row">
        <span className="k">kV</span>
        <input
          value={kv}
          style={{ width: 44 }}
          onChange={(e) => setKv(e.target.value)}
        />
        <span className="k">Cs mm</span>
        <input
          value={cs}
          style={{ width: 40 }}
          onChange={(e) => setCs(e.target.value)}
        />
        <span className="k">Å/px</span>
        <input
          value={pxA}
          style={{ width: 44 }}
          onChange={(e) => setPxA(e.target.value)}
        />
        <button
          className="fvd-btn primary"
          onClick={run}
          disabled={busy}
          title="Fit the CTF to estimate defocus (Δf), λ and R²"
        >
          {busy ? "Fitting…" : "Estimate"}
        </button>
      </div>
      {res && (
        <div className="fvd-ws-note">
          Δf = {res.defocus_nm.toFixed(1)} nm · R² = {res.r_squared.toFixed(3)}{" "}
          · λ = {res.lambda_a.toFixed(4)} Å
        </div>
      )}
      {res && <div ref={host} className="fvd-ws-plot" />}
    </>
  );
}

// ── Lattice (two clicks on an FFT) ───────────────────────────────────

function LatticeMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const [spots, setSpots] = useState<[number, number][]>([]);
  const [table, setTable] = useState<Record<string, string> | null>(null);

  useEffect(() => {
    setSpots([]);
    setTable(null);
  }, [id]);

  const onClick = (rc: [number, number]) => {
    const next = [...spots, rc].slice(-2) as [number, number][];
    setSpots(next);
    setTable(null);
    if (next.length === 2) {
      analyzeLattice(id, next[0], next[1])
        .then((r) =>
          setTable({
            a: `${r.a.toFixed(3)} ${r.unit}`,
            b: `${r.b.toFixed(3)} ${r.unit}`,
            γ: `${r.gamma_deg.toFixed(2)}°`,
            "d₁": `${r.d_spacing1.toFixed(3)} ${r.unit}`,
            "d₂": `${r.d_spacing2.toFixed(3)} ${r.unit}`,
            A_cell: `${r.unit_cell_area.toFixed(4)} ${r.unit}²`,
          }),
        )
        .catch((e: Error) => setStatus(`lattice: ${e.message}`));
    }
  };

  return (
    <>
      <Preview
        id={id}
        markers={spots.map(([r, c]) => ({ x: c, y: r }))}
        color="var(--capture)"
        onClick={onClick}
      />
      <div className="fvd-ws-note">
        {spots.length < 2
          ? `Open the FFT of a lattice image, then click ${2 - spots.length}
             more spot${spots.length === 1 ? "" : "s"}.`
          : "Click again to restart."}
      </div>
      {table && (
        <table className="fvd-ws-table">
          <tbody>
            {Object.entries(table).map(([k, v]) => (
              <tr key={k}>
                <td>{k}</td>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

// ── Stitch ───────────────────────────────────────────────────────────

function StitchMode() {
  const selected = useViewer((s) => s.selected);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const setStatus = useViewer((s) => s.setStatus);
  const [layout, setLayout] = useState("horizontal");
  const [overlap, setOverlap] = useState("0.2");
  const [busy, setBusy] = useState(false);

  const run = () => {
    setBusy(true);
    analyzeStitch(selected, {
      layout,
      overlapFrac: Number(overlap) || 0.2,
    })
      .then((r) => {
        ingestDerived([r.mosaic]);
        setStatus(`stitched ${selected.length} tiles → ${r.mosaic.name}`);
      })
      .catch((e: Error) => setStatus(`stitch: ${e.message}`))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <div className="fvd-ws-row">
        <div className="fvd-seg">
          {["horizontal", "vertical", "grid"].map((l) => (
            <button
              key={l}
              className={`fvd-seg-btn${layout === l ? " active" : ""}`}
              onClick={() => setLayout(l)}
              title={`Arrange tiles in a ${l} layout`}
            >
              {l}
            </button>
          ))}
        </div>
      </div>
      <div className="fvd-ws-row">
        <span className="k">overlap</span>
        <input
          value={overlap}
          style={{ width: 44 }}
          onChange={(e) => setOverlap(e.target.value)}
        />
        <button
          className="fvd-btn primary"
          onClick={run}
          disabled={busy || selected.length < 2}
          title="Stitch the selected tiles into one mosaic"
        >
          {busy ? "Stitching…" : `Stitch ${selected.length} tiles`}
        </button>
      </div>
      <div className="fvd-ws-note">
        ⌘-click tiles in the filmstrip (equal sizes required), in acquisition
        order.
      </div>
    </>
  );
}
