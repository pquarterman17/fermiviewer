// Diffraction workshop (handoff §4 Inspector · Diffraction): spot
// detection overlaid on the pattern, camera geometry, phase indexing,
// matched-phase rings (port of drawMatchedRings.m), typed-d ring overlay,
// and analysis-ROI drawing (rect / circle) to scope detect + index.

import { useCallback, useEffect, useRef, useState } from "react";

import {
  DiffractionCalibrationPanel,
  DiffractionIndexPanel,
  DiffractionSimulationPanel,
} from "./DiffractionPanels";

import {
  analyzeDiffractionSimulate,
  deleteDiffractionPhase,
  diffractionCalibrate,
  diffractionDetect,
  diffractionDetectWithRoi,
  diffractionIndex,
  importDiffractionPhase,
  listDiffractionPhases,
  renderUrl,
  type AnalysisRoi,
  type CalibrationResult,
  type IndexResult,
  type PhaseCandidate,
  type PhaseInfo,
  type SimulateResult,
} from "../../lib/api";
import {
  committedRoiOverlay,
  liveRoiDrawOverlay,
} from "./diffraction/DiffractionOverlays";
import {
  dSpacingToRadiusPx,
  matchedRingSvg,
  matchedSpotIndices,
  roiFromPoints,
  type RoiDraw,
  type RoiMode,
} from "./diffraction/diffractionGeometry";
import {
  downloadCsv,
  downloadJson,
  exportBaseName,
  tableToCsv,
  tableToJson,
  type Cell,
} from "../../lib/resultsExport";
import { useViewer } from "../../store/viewer";

export { matchedSpotIndices } from "./diffraction/diffractionGeometry";

const VIEW_W = 300;

type WorkshopTab = "index" | "calibrate" | "simulate";

export default function DiffractionWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const setStatus = useViewer((s) => s.setStatus);
  const [tab, setTab] = useState<WorkshopTab>("index");

  const [minRadius, setMinRadius] = useState("10");
  const [threshold, setThreshold] = useState("0.05");
  const [pixelSize, setPixelSize] = useState("1.0");
  const [cameraLen, setCameraLen] = useState("");
  const [accKv, setAccKv] = useState("200");
  const [spots, setSpots] = useState<[number, number][]>([]);
  const [indexResult, setIndexResult] = useState<IndexResult | null>(null);
  const [candidates, setCandidates] = useState<PhaseCandidate[]>([]);
  const [selectedCandIdx, setSelectedCandIdx] = useState(0);
  const [rings, setRings] = useState(false);
  const [labels, setLabels] = useState(false);
  const [busy, setBusy] = useState(false);
  // A8 simulate
  const [phases, setPhases] = useState<PhaseInfo[]>([]);
  const [simPhase, setSimPhase] = useState("");
  const [simZa, setSimZa] = useState("0 0 1");
  const [simResult, setSimResult] = useState<SimulateResult | null>(null);
  const [scatModel, setScatModel] = useState<"fe" | "z">("fe");
  const cifInputRef = useRef<HTMLInputElement>(null);
  // calibration sub-panel
  const [calKnownD, setCalKnownD] = useState("");
  const [calib, setCalib] = useState<CalibrationResult | null>(null);
  // A7 manual click-spots
  const [clickMode, setClickMode] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);

  // Typed d-spacing ring
  const [typedD, setTypedD] = useState("");

  // Analysis ROI
  const [roiMode, setRoiMode] = useState<RoiMode>("none");
  const [roiDraw, setRoiDraw] = useState<RoiDraw>({ mode: "none", p1: null, p2: null });
  const [committedRoi, setCommittedRoi] = useState<AnalysisRoi | null>(null);

  const isImage = meta?.kind === "image";

  useEffect(() => {
    setSpots([]);
    setCandidates([]);
    setIndexResult(null);
    setNatural(null);
    setCommittedRoi(null);
    setRoiDraw({ mode: "none", p1: null, p2: null });
    setRoiMode("none");
  }, [activeId]);

  useEffect(() => {
    listDiffractionPhases()
      .then((list) => {
        setPhases(list);
        if (list.length > 0) setSimPhase(list[0].name);
      })
      .catch(() => undefined);
  }, []);

  const scale = natural ? VIEW_W / natural.w : 0;
  const viewH = natural ? natural.h * scale : VIEW_W;

  // ── ROI SVG geometry for the committed ROI overlay ──────────────────
  const roiSvgEl = committedRoiOverlay(committedRoi, scale);

  // ── ROI live-draw overlay (while user is drawing) ─────────────────
  const liveDraw = liveRoiDrawOverlay(roiDraw);

  // ── detect ────────────────────────────────────────────────────────
  const detect = useCallback(() => {
    if (!activeId) return;
    setBusy(true);
    diffractionDetectWithRoi(activeId, {
      minRadius: Number(minRadius) || 10,
      threshold: Number(threshold) || 0.05,
      roi: committedRoi ?? undefined,
    })
      .then((r) => {
        setSpots(r.spots);
        setStatus(`diffraction: ${r.n} spots${committedRoi ? " (ROI)" : ""}`);
      })
      .catch((e: Error) => setStatus(`detect: ${e.message}`))
      .finally(() => setBusy(false));
  }, [activeId, minRadius, threshold, committedRoi, setStatus]);

  // ── detect (legacy no-ROI, kept so the old diffractionDetect import doesn't break) ──
  const detectLegacy = useCallback(() => {
    if (!activeId) return;
    setBusy(true);
    diffractionDetect(activeId, {
      minRadius: Number(minRadius) || 10,
      threshold: Number(threshold) || 0.05,
    })
      .then((r) => {
        setSpots(r.spots);
        setStatus(`diffraction: ${r.n} spots`);
      })
      .catch((e: Error) => setStatus(`detect: ${e.message}`))
      .finally(() => setBusy(false));
  }, [activeId, minRadius, threshold, setStatus]);
  void detectLegacy; // retained for compatibility, detect() is the primary path

  // ── index ─────────────────────────────────────────────────────────
  const index = useCallback(() => {
    if (!activeId || spots.length === 0) return;
    setBusy(true);
    diffractionIndex(activeId, spots, {
      pixelSizeMm: Number(pixelSize) || 1.0,
      cameraLengthMm: cameraLen ? Number(cameraLen) : undefined,
      accKv: Number(accKv) || 200,
      roi: committedRoi ?? undefined,
    })
      .then((r) => {
        setIndexResult(r);
        setCandidates(r.candidates);
        setSelectedCandIdx(0);
      })
      .catch((e: Error) => setStatus(`index: ${e.message}`))
      .finally(() => setBusy(false));
  }, [activeId, spots, pixelSize, cameraLen, accKv, committedRoi, setStatus]);

  // ── simulate ──────────────────────────────────────────────────────
  const simulate = useCallback(() => {
    if (!simPhase) return;
    const parts = simZa.trim().split(/\s+/).map(Number);
    if (parts.length !== 3 || parts.some(isNaN)) {
      setStatus("Simulate: zone axis must be three integers, e.g. 0 0 1");
      return;
    }
    setBusy(true);
    analyzeDiffractionSimulate(simPhase, parts as [number, number, number], {
      parentImageId: activeId ?? undefined,
      scatteringModel: scatModel,
    })
      .then((r) => {
        setSimResult(r);
        setStatus(
          `sim: ${r.phase} [${r.zone_axis.join(" ")}] · ` +
            `${r.spots.length} spots · λ ${r.lam_angstrom.toFixed(4)} Å`,
        );
        if (r.image) {
          useViewer.getState().ingestDerived([r.image]);
        }
      })
      .catch((e: Error) => setStatus(`simulate: ${e.message}`))
      .finally(() => setBusy(false));
  }, [simPhase, simZa, activeId, scatModel, setStatus]);

  // ── custom-phase import / delete (Diffraction #2) ─────────────────
  const onCifFile = useCallback(
    (file: File) => {
      file
        .text()
        .then((text) => importDiffractionPhase(text, ""))
        .then((p) => {
          setStatus(`phase imported: ${p.name} (${p.centering}, ${p.n_sites} sites)`);
          return listDiffractionPhases();
        })
        .then((list) => {
          setPhases(list);
          const last = list.find((p) => p.custom);
          if (last) setSimPhase(last.name);
        })
        .catch((e: Error) => setStatus(`CIF import: ${e.message}`));
    },
    [setStatus],
  );

  const deletePhase = useCallback(() => {
    const p = phases.find((x) => x.name === simPhase);
    if (!p?.custom) return;
    deleteDiffractionPhase(p.name)
      .then(() => listDiffractionPhases())
      .then((list) => {
        setPhases(list);
        setSimPhase(list[0]?.name ?? "");
        setStatus(`phase deleted: ${p.name}`);
      })
      .catch((e: Error) => setStatus(`delete: ${e.message}`));
  }, [phases, simPhase, setStatus]);

  // ── elliptical-distortion calibration (Diffraction #1) ────────────
  const calibrate = useCallback(() => {
    if (!activeId) return;
    const dKnown = Number(calKnownD);
    setBusy(true);
    diffractionCalibrate(activeId, {
      dKnownAng: dKnown > 0 ? dKnown : undefined,
      standardPhase: dKnown > 0 ? undefined : simPhase || undefined,
      hkl: dKnown > 0 ? undefined : [1, 1, 1],
      rMin: Number(minRadius) || 5,
    })
      .then((r) => {
        setCalib(r);
        const e = r.ellipse;
        setStatus(
          `calibrate: ecc ${e.eccentricity.toFixed(3)} · ` +
            `a/b ${e.a.toFixed(1)}/${e.b.toFixed(1)} px · ` +
            `RMS ${r.rms_residual_px.toFixed(2)} px` +
            (r.camera_constant_px_ang
              ? ` · C ${r.camera_constant_px_ang.toFixed(1)} px·Å`
              : ""),
        );
      })
      .catch((e: Error) => setStatus(`calibrate: ${e.message}`))
      .finally(() => setBusy(false));
  }, [activeId, calKnownD, simPhase, minRadius, setStatus]);

  if (!isImage) {
    return (
      <div className="fvd-ws-empty">
        Select a 2D diffraction pattern (or run FFT on a lattice image).
      </div>
    );
  }

  const HIT_R = 6;

  // ── SVG interaction — ROI drawing takes priority over spot clicking ──
  const onSvgMouseDown = (e: React.MouseEvent<SVGSVGElement>) => {
    if (roiMode !== "none") {
      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      setRoiDraw({ mode: roiMode, p1: { x, y }, p2: { x, y } });
      return;
    }
    // click-spots mode
    if (!clickMode || !natural || scale === 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const col = sx / scale + 0.5;
    const row = sy / scale + 0.5;
    const hit = spots.findIndex(([sr, sc]) => {
      const dx = (sc - col) * scale;
      const dy = (sr - row) * scale;
      return Math.hypot(dx, dy) <= HIT_R;
    });
    if (hit >= 0) {
      setSpots(spots.filter((_, i) => i !== hit));
    } else {
      setSpots([...spots, [row, col]]);
    }
  };

  const onSvgMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (roiDraw.p1 && roiMode !== "none") {
      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      setRoiDraw((d) => ({ ...d, p2: { x, y } }));
    }
  };

  const onSvgMouseUp = (e: React.MouseEvent<SVGSVGElement>) => {
    if (roiDraw.p1 && roiMode !== "none") {
      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const finalDraw = { ...roiDraw, p2: { x, y } };
      const roi = roiFromPoints(finalDraw, scale);
      if (roi) setCommittedRoi(roi);
      setRoiDraw({ mode: "none", p1: null, p2: null });
      setRoiMode("none");
    }
  };

  // ── typed-d ring radius in display pixels ─────────────────────────
  const typedDVal = parseFloat(typedD);
  const typedRingR =
    typedDVal > 0 && natural && scale > 0
      ? dSpacingToRadiusPx(
          typedDVal,
          natural.w,
          Number(pixelSize) || 1.0,
          cameraLen ? Number(cameraLen) : null,
          Number(accKv) || 200,
          scale,
        )
      : null;

  // ── matched-ring SVG nodes for the selected candidate ────────────
  const matchedRingNodes =
    (rings || labels) && indexResult && candidates.length > 0 && natural
      ? matchedRingSvg(
          candidates[selectedCandIdx] ?? candidates[0],
          indexResult.measured_r,
          indexResult.center as [number, number],
          scale,
          natural.w,
          Number(pixelSize) || 1.0,
          spots,
          rings,
          labels,
        )
      : [];

  // ── indexing report (#4): per-matched-spot table + provenance header ──
  const buildReportTable = (): {
    columns: string[];
    rows: Cell[][];
    meta: Record<string, unknown>;
  } | null => {
    if (!indexResult || candidates.length === 0) return null;
    const c = candidates[selectedCandIdx] ?? candidates[0];
    const idx = matchedSpotIndices(
      c,
      indexResult.measured_r,
      natural?.w ?? 0,
      Number(pixelSize) || 1,
    );
    const columns = [
      "#", "row", "col", "r (px)", "d_meas (Å)", "d_ref (Å)", "hkl", "rel err (%)",
    ];
    const rows: Cell[][] = c.matched_d.map((dMeas, k) => {
      const i = idx[k];
      const sp = i >= 0 ? spots[i] : undefined;
      const relErr =
        c.ref_d[k] ? (Math.abs(dMeas - c.ref_d[k]) / c.ref_d[k]) * 100 : null;
      return [
        k + 1,
        sp ? sp[0] : null,
        sp ? sp[1] : null,
        sp ? indexResult.measured_r[i] : null,
        dMeas,
        c.ref_d[k],
        `(${(c.matched_hkl[k] ?? []).join(" ")})`,
        relErr,
      ];
    });
    return {
      columns,
      rows,
      meta: {
        imageName: meta?.name,
        analysis: "Diffraction indexing",
        params: {
          phase: c.phase,
          formula: c.formula,
          zone_axis: `[${c.zone_axis.join(" ")}]`,
          score: c.score,
          n_matched: c.n_matched,
          pixel_size: Number(pixelSize) || 1,
          camera_length_mm: cameraLen ? Number(cameraLen) : "FFT mode",
          acc_voltage_kv: Number(accKv) || 200,
        },
      },
    };
  };

  const downloadReport = (fmt: "csv" | "json") => {
    const t = buildReportTable();
    if (!t) return;
    const base = `${exportBaseName(meta?.name)}_indexing`;
    if (fmt === "csv") downloadCsv(`${base}.csv`, tableToCsv(t.columns, t.rows, t.meta));
    else downloadJson(`${base}.json`, tableToJson(t.columns, t.rows, t.meta));
    setStatus(`indexing report: ${t.rows.length} matched spots`);
  };

  const svgCursor =
    roiMode !== "none"
      ? "crosshair"
      : clickMode
        ? "crosshair"
        : "default";

  // ── pattern centre for SVG (1-based → display) ───────────────────
  const patternCx = natural ? ((natural.w / 2 + 0.5) - 0.5) * scale : 0;
  const patternCy = natural ? ((natural.h / 2 + 0.5) - 0.5) * scale : 0;

  return (
    <div className="fvd-ws">
      <div className="fvd-ws-pattern" style={{ width: VIEW_W, height: viewH }}>
        {activeId && (
          <img
            ref={imgRef}
            src={renderUrl(activeId)}
            alt="pattern"
            width={VIEW_W}
            draggable={false}
            onLoad={(e) => {
              const el = e.currentTarget;
              setNatural({ w: el.naturalWidth, h: el.naturalHeight });
            }}
          />
        )}
        {natural && (
          <svg
            width={VIEW_W}
            height={viewH}
            onMouseDown={onSvgMouseDown}
            onMouseMove={onSvgMouseMove}
            onMouseUp={onSvgMouseUp}
            style={{ cursor: svgCursor }}
          >
            {/* detected spots */}
            {spots.map(([r, c], i) => (
              <circle
                key={i}
                cx={(c - 0.5) * scale}
                cy={(r - 0.5) * scale}
                r={clickMode ? 6 : 4}
                fill={clickMode ? "rgba(var(--capture-rgb,53,224,194),0.2)" : "none"}
                stroke="var(--capture)"
                strokeWidth={1.5}
                style={{ cursor: clickMode ? "pointer" : "default" }}
              />
            ))}

            {/* matched-phase rings (port of drawMatchedRings.m) */}
            {matchedRingNodes}

            {/* typed d-spacing ring */}
            {typedRingR !== null && typedRingR > 0 && (
              <g>
                <circle
                  cx={patternCx}
                  cy={patternCy}
                  r={typedRingR}
                  fill="none"
                  stroke="#f59e0b"
                  strokeWidth={1.2}
                  strokeDasharray="6 3"
                />
                <text
                  x={patternCx + typedRingR * 0.72}
                  y={patternCy - typedRingR * 0.72}
                  fill="#f59e0b"
                  fontSize={8}
                  dominantBaseline="middle"
                >
                  {typedDVal.toFixed(3)} Å
                </text>
              </g>
            )}

            {/* committed ROI overlay */}
            {roiSvgEl}

            {/* live ROI drawing */}
            {liveDraw}
          </svg>
        )}
      </div>

      <div className="fvd-seg" role="tablist" aria-label="Diffraction tasks">
        <button className={`fvd-seg-btn${tab === "index" ? " active" : ""}`} role="tab" aria-selected={tab === "index"} onClick={() => setTab("index")}>Index</button>
        <button className={`fvd-seg-btn${tab === "calibrate" ? " active" : ""}`} role="tab" aria-selected={tab === "calibrate"} onClick={() => setTab("calibrate")}>Calibrate</button>
        <button className={`fvd-seg-btn${tab === "simulate" ? " active" : ""}`} role="tab" aria-selected={tab === "simulate"} onClick={() => setTab("simulate")}>Simulate</button>
      </div>
      {tab === "index" && (
        <DiffractionIndexPanel
          minRadius={minRadius} setMinRadius={setMinRadius}
          threshold={threshold} setThreshold={setThreshold}
          pixelSize={pixelSize} setPixelSize={setPixelSize}
          cameraLen={cameraLen} setCameraLen={setCameraLen}
          accKv={accKv} setAccKv={setAccKv} busy={busy} detect={detect}
          rings={rings} setRings={setRings} labels={labels} setLabels={setLabels}
          clickMode={clickMode} setClickMode={setClickMode} spotsLength={spots.length}
          typedD={typedD} setTypedD={setTypedD} typedRingR={typedRingR}
          index={index} candidates={candidates} selectedCandIdx={selectedCandIdx}
          setSelectedCandIdx={setSelectedCandIdx} downloadReport={downloadReport}
          roiMode={roiMode} setRoiMode={setRoiMode} committedRoi={committedRoi}
          clearRoi={() => {
            setCommittedRoi(null);
            setRoiDraw({ mode: "none", p1: null, p2: null });
            setRoiMode("none");
          }}
        />
      )}
      {tab === "calibrate" && (
        <DiffractionCalibrationPanel calKnownD={calKnownD} setCalKnownD={setCalKnownD}
          busy={busy} activeId={activeId} calibrate={calibrate} calib={calib} />
      )}
      {tab === "simulate" && (
        <DiffractionSimulationPanel phases={phases} simPhase={simPhase}
          setSimPhase={setSimPhase} cifInputRef={cifInputRef} onCifFile={onCifFile}
          deletePhase={deletePhase} scatModel={scatModel} setScatModel={setScatModel}
          simZa={simZa} setSimZa={setSimZa} simulate={simulate} busy={busy}
          simResult={simResult} />
      )}
    </div>
  );
}
