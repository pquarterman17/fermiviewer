// Diffraction workshop (handoff §4 Inspector · Diffraction): spot
// detection overlaid on the pattern, camera geometry, phase indexing,
// matched-phase rings (port of drawMatchedRings.m), typed-d ring overlay,
// and analysis-ROI drawing (rect / circle) to scope detect + index.

import { useCallback, useEffect, useRef, useState } from "react";

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
  downloadCsv,
  downloadJson,
  exportBaseName,
  tableToCsv,
  tableToJson,
  type Cell,
} from "../../lib/resultsExport";
import { useViewer } from "../../store/viewer";

const VIEW_W = 300;

// ── ROI drawing state ────────────────────────────────────────────────
type RoiMode = "none" | "rect" | "circle";

interface RoiDraw {
  mode: RoiMode;
  p1: { x: number; y: number } | null; // first click (display px)
  p2: { x: number; y: number } | null; // second click / live drag
}

/** Convert display-px point to 0-based full-image coords. */
function toImg(pt: { x: number; y: number }, scale: number) {
  return { r: Math.round(pt.y / scale), c: Math.round(pt.x / scale) };
}

/** Build an AnalysisRoi from two display-px points given a display scale. */
function roiFromPoints(
  draw: RoiDraw,
  scale: number,
): AnalysisRoi | null {
  if (!draw.p1 || !draw.p2) return null;
  const a = toImg(draw.p1, scale);
  const b = toImg(draw.p2, scale);
  if (draw.mode === "rect") {
    return {
      kind: "rect",
      r0: Math.min(a.r, b.r),
      c0: Math.min(a.c, b.c),
      r1: Math.max(a.r, b.r),
      c1: Math.max(a.c, b.c),
    };
  }
  if (draw.mode === "circle") {
    const radius = Math.round(Math.hypot(b.r - a.r, b.c - a.c));
    return { kind: "circle", cr: a.r, cc: a.c, radius };
  }
  return null;
}

// ── matched-ring helpers ─────────────────────────────────────────────

/** Build SVG ring overlays for a matched-phase candidate.
 *
 *  Port of drawMatchedRings.m:
 *    for k = 1:numel(candidate.matchedD)
 *        R = measuredR(k);
 *        plot ring at radius R centred on the pattern centre
 *        label with (hkl) at 1.05 R
 *
 *  In MATLAB, measuredR is the full array of spot radii AND matchedD is
 *  the subset for matched spots; MATLAB uses matchedD length to index
 *  measuredR sequentially.  The Python port stores matched_d as the
 *  d-spacings for matched spots.  We reconstruct which original spot
 *  corresponds to each matched_d by finding the spot whose measured radius
 *  yields the closest d-spacing via the FFT formula (d = W*px/R), greedily
 *  consuming spot indices in order — matching the MATLAB is=1:nSpots loop.
 *
 *  imgW: full image width (pixels), used for FFT-mode d↔R conversion.
 *  pixelSizeMm: pixel calibration (forwarded from the index call).
 */
/** Map each matched spot k → its index into the posted spots[]. Prefers the
 *  exact `matched_idx` from the index response; falls back to the old greedy
 *  radius reconstruction for responses that predate that field. */
export function matchedSpotIndices(
  candidate: PhaseCandidate,
  measuredR: number[],
  imgW: number,
  pixelSizeMm: number,
): number[] {
  const { matched_d, matched_idx } = candidate;
  if (Array.isArray(matched_idx) && matched_idx.length === matched_d.length) {
    return matched_idx;
  }
  // legacy fallback: d_meas[i] = W*px/R[i], greedily match each matched_d
  const dPerSpot = measuredR.map((R) =>
    R > 0 ? (imgW * pixelSizeMm) / R : Infinity,
  );
  const used = new Set<number>();
  return matched_d.map((dm) => {
    let best = -1;
    let bestFrac = Infinity;
    for (let i = 0; i < dPerSpot.length; i++) {
      if (used.has(i)) continue;
      const frac = Math.abs(dPerSpot[i] - dm) / dm;
      if (frac < bestFrac) {
        bestFrac = frac;
        best = i;
      }
    }
    if (best >= 0) used.add(best);
    return best;
  });
}

function matchedRingSvg(
  candidate: PhaseCandidate,
  measuredR: number[],
  center: [number, number],   // 1-based (row, col)
  scale: number,
  imgW: number,
  pixelSizeMm: number,
  spots: [number, number][],
  showRings: boolean,
  showLabels: boolean,
): React.ReactNode[] {
  const cx = (center[1] - 0.5) * scale;  // 1-based col → display px
  const cy = (center[0] - 0.5) * scale;
  const nodes: React.ReactNode[] = [];
  const { matched_hkl, matched_d } = candidate;
  if (!matched_d || matched_d.length === 0 || measuredR.length === 0) return [];

  const idx = matchedSpotIndices(candidate, measuredR, imgW, pixelSizeMm);

  for (let k = 0; k < matched_d.length; k++) {
    const i = idx[k];
    if (i < 0 || i >= measuredR.length) continue;
    const R = measuredR[i] * scale;
    const hkl = matched_hkl[k] ?? [0, 0, 0];

    if (showRings) {
      nodes.push(
        <circle key={`mring-${k}`} cx={cx} cy={cy} r={R} fill="none"
          stroke="#22c55e" strokeWidth={1} />,
      );
      // on-ring hkl tag only when per-spot labels aren't carrying it
      if (!showLabels) {
        nodes.push(
          <text key={`mrt-${k}`} x={cx + R * 1.05} y={cy} fill="#22c55e"
            fontSize={9} dominantBaseline="middle">
            ({hkl.join("")})
          </text>,
        );
      }
    }

    // #4: hkl + measured-d label pinned at the matched spot's own position
    if (showLabels && spots[i]) {
      const [row, col] = spots[i];
      const sx = (col - 0.5) * scale;
      const sy = (row - 0.5) * scale;
      nodes.push(
        <g key={`mlbl-${k}`}>
          <circle cx={sx} cy={sy} r={3} fill="#22c55e" />
          <text x={sx + 6} y={sy - 4} fill="#22c55e" fontSize={9}
            dominantBaseline="middle" stroke="#000" strokeWidth={0.5}
            paintOrder="stroke">
            ({hkl.join("")}) {matched_d[k].toFixed(3)}Å
          </text>
        </g>,
      );
    }
  }
  return nodes;
}

// ── d-spacing → radius (FFT mode, frontend mirror of d_spacing_to_radius) ──

/** Convert a d-spacing (Å) to a ring radius in display pixels.
 *
 *  FFT mode formula (drawRingOverlay.m / d_spacing_to_radius in calc):
 *    R_px = W * pixelSize / d
 *  where W = image width in px, pixelSize in Å/px.
 *
 *  Camera-mode formula (when cameraLengthMm is provided):
 *    sin θ = λ / (2 d);  R_px = L_mm * tan(2θ) / pixelSize_mm_per_px
 *  λ (Å) = 12.264 / sqrt(kV * (1 + 0.9788e-3 * kV)) [non-relativistic approx
 *  used here only for display preview; the backend uses the exact CODATA formula].
 */
function dSpacingToRadiusPx(
  dAng: number,
  imgW: number,
  pixelSizeMm: number,
  cameraLengthMm: number | null,
  accKv: number,
  displayScale: number,
): number | null {
  if (dAng <= 0) return null;
  if (!cameraLengthMm) {
    // FFT mode: pixel_size treated as Å/px (the workshop stores mm, but for
    // FFT-mode the user typically enters the real-space calibration in nm or
    // similar; the backend always uses consistent units — here we mirror the
    // FFT formula for the preview ring without unit-conversion since the scale
    // only matters relatively): R_img = W * pixelSize / d
    const rImg = (imgW * pixelSizeMm) / dAng;
    return rImg * displayScale;
  }
  // TEM camera mode
  const kv = accKv;
  const lam = 12.264 / Math.sqrt(kv * (1 + 0.9788e-3 * kv)); // Å approx
  const sinTheta = lam / (2 * dAng);
  if (sinTheta > 1) return null;
  const rMm = cameraLengthMm * Math.tan(2 * Math.asin(sinTheta));
  const rImg = rMm / pixelSizeMm;
  return rImg * displayScale;
}

export default function DiffractionWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const setStatus = useViewer((s) => s.setStatus);

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
  const roiSvgEl = (() => {
    if (!committedRoi || !scale) return null;
    if (committedRoi.kind === "rect") {
      const { r0, c0, r1, c1 } = committedRoi;
      return (
        <rect
          x={c0 * scale}
          y={r0 * scale}
          width={(c1 - c0) * scale}
          height={(r1 - r0) * scale}
          fill="none"
          stroke="var(--capture, #35e0c2)"
          strokeWidth={1.5}
          strokeDasharray="5 3"
        />
      );
    }
    if (committedRoi.kind === "circle") {
      const { cr, cc, radius } = committedRoi;
      return (
        <circle
          cx={cc * scale}
          cy={cr * scale}
          r={radius * scale}
          fill="none"
          stroke="var(--capture, #35e0c2)"
          strokeWidth={1.5}
          strokeDasharray="5 3"
        />
      );
    }
    return null;
  })();

  // ── ROI live-draw overlay (while user is drawing) ─────────────────
  const liveDraw = (() => {
    if (!roiDraw.p1 || !roiDraw.p2 || roiDraw.mode === "none") return null;
    const x1 = roiDraw.p1.x, y1 = roiDraw.p1.y;
    const x2 = roiDraw.p2.x, y2 = roiDraw.p2.y;
    if (roiDraw.mode === "rect") {
      return (
        <rect
          x={Math.min(x1, x2)} y={Math.min(y1, y2)}
          width={Math.abs(x2 - x1)} height={Math.abs(y2 - y1)}
          fill="rgba(53,224,194,0.08)"
          stroke="var(--capture, #35e0c2)"
          strokeWidth={1}
          strokeDasharray="4 3"
        />
      );
    }
    const r = Math.hypot(x2 - x1, y2 - y1);
    return (
      <circle cx={x1} cy={y1} r={r}
        fill="rgba(53,224,194,0.08)"
        stroke="var(--capture, #35e0c2)"
        strokeWidth={1} strokeDasharray="4 3"
      />
    );
  })();

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

      {/* detect controls */}
      <div className="fvd-ws-row">
        <span className="k">min r</span>
        <input
          value={minRadius}
          style={{ width: 44 }}
          onChange={(e) => setMinRadius(e.target.value)}
        />
        <span className="k">thresh</span>
        <input
          value={threshold}
          style={{ width: 52 }}
          onChange={(e) => setThreshold(e.target.value)}
        />
        <button
          className="fvd-btn"
          title="Detect diffraction spots (uses min r + threshold, and ROI if set)"
          onClick={detect}
          disabled={busy}
        >
          Detect
        </button>
        <label className="fvd-check">
          <input
            type="checkbox"
            checked={rings}
            onChange={(e) => setRings(e.target.checked)}
          />
          Rings
        </label>
        <label
          className="fvd-check"
          title="label each matched spot with its (hkl) + measured d on the pattern"
        >
          <input
            type="checkbox"
            checked={labels}
            onChange={(e) => setLabels(e.target.checked)}
          />
          Labels
        </label>
      </div>

      {/* click-spot mode */}
      <div className="fvd-ws-row">
        <button
          className={`fvd-btn${clickMode ? " active" : ""}`}
          onClick={() => setClickMode((v) => !v)}
          title="Click spots manually on the pattern preview (A7)"
        >
          {clickMode ? "Done Clicking" : "Click Spots"}
        </button>
        {clickMode && (
          <span className="fvd-ws-hint">Click to add · click existing to remove</span>
        )}
        {spots.length > 0 && !clickMode && (
          <span className="fvd-ws-hint">{spots.length} spots</span>
        )}
      </div>

      {/* typed d-spacing ring overlay */}
      <div className="fvd-ws-row">
        <span className="k">d (Å)</span>
        <input
          value={typedD}
          style={{ width: 64 }}
          placeholder="e.g. 2.338"
          title="Type a d-spacing (Å) to preview the matching ring on the pattern"
          onChange={(e) => setTypedD(e.target.value)}
        />
        {typedRingR !== null ? (
          <span className="fvd-ws-hint">{typedRingR.toFixed(1)} px</span>
        ) : typedD ? (
          <span className="fvd-ws-hint" style={{ color: "var(--error, #f87171)" }}>
            out of range
          </span>
        ) : null}
      </div>

      {/* index controls */}
      <div className="fvd-ws-row">
        <span className="k">px (mm)</span>
        <input
          value={pixelSize}
          style={{ width: 52 }}
          onChange={(e) => setPixelSize(e.target.value)}
        />
        <span className="k">L (mm)</span>
        <input
          value={cameraLen}
          placeholder="auto"
          style={{ width: 52 }}
          onChange={(e) => setCameraLen(e.target.value)}
        />
        <span className="k">kV</span>
        <input
          value={accKv}
          style={{ width: 44 }}
          onChange={(e) => setAccKv(e.target.value)}
        />
        <button
          className="fvd-btn"
          title="Index the detected spots against candidate phases"
          onClick={index}
          disabled={busy || spots.length === 0}
        >
          Index
        </button>
      </div>

      {/* phase candidates table with selection */}
      {candidates.length > 0 && (
        <table className="fvd-ws-table">
          <thead>
            <tr>
              <th></th>
              <th>Phase</th>
              <th>Zone</th>
              <th>Matched</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c, i) => (
              <tr
                key={`${c.phase}-${c.zone_axis.join("")}`}
                style={{
                  cursor: "pointer",
                  background: i === selectedCandIdx ? "rgba(34,197,94,0.12)" : undefined,
                }}
                onClick={() => setSelectedCandIdx(i)}
              >
                <td>{i === selectedCandIdx ? "●" : ""}</td>
                <td title={c.formula}>{c.phase}</td>
                <td>[{c.zone_axis.join(" ")}]</td>
                <td>{c.n_matched}</td>
                <td>{c.score.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {candidates.length > 0 && (
        <>
          <div className="fvd-ws-row">
            <span className="k">report</span>
            <button
              className="fvd-btn"
              disabled={(candidates[selectedCandIdx]?.n_matched ?? 0) === 0}
              title="Download the measured-vs-reference indexing table (CSV)"
              onClick={() => downloadReport("csv")}
            >
              CSV
            </button>
            <button
              className="fvd-btn"
              disabled={(candidates[selectedCandIdx]?.n_matched ?? 0) === 0}
              title="Download the indexing report with provenance (JSON)"
              onClick={() => downloadReport("json")}
            >
              JSON
            </button>
          </div>
          <div className="fvd-ws-note" style={{ fontSize: 10 }}>
            Click a row to select · Rings overlays d-spacings · Labels tags each
            spot with (hkl) + d
          </div>
        </>
      )}

      {/* Analysis ROI controls */}
      <div className="fvd-ws-section" style={{ marginTop: 6 }}>
        <span>Analysis ROI</span>
      </div>
      <div className="fvd-ws-row">
        <button
          className={`fvd-btn${roiMode === "rect" ? " active" : ""}`}
          title="Draw a rectangular ROI — detect/index will use only this region"
          onClick={() => setRoiMode((m) => (m === "rect" ? "none" : "rect"))}
        >
          Rect
        </button>
        <button
          className={`fvd-btn${roiMode === "circle" ? " active" : ""}`}
          title="Draw a circular ROI — click centre then edge"
          onClick={() => setRoiMode((m) => (m === "circle" ? "none" : "circle"))}
        >
          Circle
        </button>
        <button
          className="fvd-btn"
          title="Clear the Analysis ROI — detect/index revert to full image"
          disabled={!committedRoi}
          onClick={() => {
            setCommittedRoi(null);
            setRoiDraw({ mode: "none", p1: null, p2: null });
            setRoiMode("none");
          }}
        >
          Clear ROI
        </button>
        {committedRoi && (
          <span className="fvd-ws-hint">
            {committedRoi.kind === "rect"
              ? `${committedRoi.c1 - committedRoi.c0}×${committedRoi.r1 - committedRoi.r0} px`
              : `r=${committedRoi.radius} px`}
          </span>
        )}
      </div>
      {roiMode !== "none" && (
        <div className="fvd-ws-note">
          {roiMode === "rect"
            ? "Drag on the pattern to draw a rect ROI"
            : "Click centre then drag to edge for circle ROI"}
        </div>
      )}

      {/* Calibration — ellipse fit + camera constant (Diffraction #1) */}
      <div className="fvd-ws-section">
        <span>Calibrate rings</span>
      </div>
      <div className="fvd-ws-row">
        <span className="k">known d (Å)</span>
        <input
          value={calKnownD}
          style={{ width: 60 }}
          placeholder="auto"
          title="known standard ring d-spacing; blank → use the selected phase's 111"
          onChange={(e) => setCalKnownD(e.target.value)}
        />
        <button
          className="fvd-btn"
          title="Fit ring ellipse to calibrate distortion & camera constant"
          onClick={calibrate}
          disabled={busy || !activeId}
        >
          Fit ellipse
        </button>
      </div>
      {calib && (
        <div className="fvd-ws-note">
          ecc {calib.ellipse.eccentricity.toFixed(3)} · a/b{" "}
          {calib.ellipse.a.toFixed(1)}/{calib.ellipse.b.toFixed(1)} px · θ{" "}
          {calib.ellipse.theta_deg.toFixed(1)}° · RMS{" "}
          {calib.rms_residual_px.toFixed(2)} px
          {calib.camera_constant_px_ang != null && (
            <> · C {calib.camera_constant_px_ang.toFixed(1)} px·Å</>
          )}
        </div>
      )}

      {/* A8 — Kinematic zone-axis simulation */}
      <div className="fvd-ws-section">
        <span>Simulate (A8)</span>
      </div>
      <div className="fvd-ws-row">
        <span className="k">Phase</span>
        <select
          value={simPhase}
          style={{ flex: 1 }}
          onChange={(e) => setSimPhase(e.target.value)}
        >
          {phases.map((p) => (
            <option key={p.name} value={p.name} title={p.formula}>
              {p.custom ? "★ " : ""}
              {p.name}
            </option>
          ))}
        </select>
        <button
          className="fvd-btn"
          title="Import a phase from a .cif file"
          onClick={() => cifInputRef.current?.click()}
        >
          + CIF
        </button>
        {phases.find((x) => x.name === simPhase)?.custom && (
          <button className="fvd-btn" title="delete this custom phase" onClick={deletePhase}>
            ✕
          </button>
        )}
        <input
          ref={cifInputRef}
          type="file"
          accept=".cif"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onCifFile(f);
            e.target.value = "";
          }}
        />
      </div>
      <div className="fvd-ws-row">
        <span className="k">intensities</span>
        <select
          value={scatModel}
          style={{ flex: 1 }}
          title="electron scattering factors (Doyle–Turner) vs the atomic-number proxy"
          onChange={(e) => setScatModel(e.target.value as "fe" | "z")}
        >
          <option value="fe">Scattering factors (Doyle–Turner)</option>
          <option value="z">Z proxy (legacy)</option>
        </select>
      </div>
      <div className="fvd-ws-row">
        <span className="k">Zone axis</span>
        <input
          value={simZa}
          style={{ width: 80 }}
          placeholder="0 0 1"
          onChange={(e) => setSimZa(e.target.value)}
        />
        <button
          className="fvd-btn"
          title="Simulate the kinematic diffraction pattern for the phase + zone axis"
          onClick={simulate}
          disabled={busy || !simPhase}
        >
          Simulate
        </button>
      </div>
      {simResult && (
        <>
          <div className="fvd-ws-note">
            {simResult.phase} ({simResult.formula}) [{simResult.zone_axis.join(" ")}
            ] · {simResult.spots.length} spots · λ{" "}
            {simResult.lam_angstrom.toFixed(4)} Å
            {simResult.image && " · pattern added to library"}
          </div>
          <table className="fvd-ws-table">
            <thead>
              <tr>
                <th>hkl</th>
                <th>d (Å)</th>
                <th>I</th>
              </tr>
            </thead>
            <tbody>
              {simResult.spots.slice(0, 12).map((s, i) => (
                <tr key={i}>
                  <td>[{s.hkl.join(" ")}]</td>
                  <td>{s.d_spacing != null ? s.d_spacing.toFixed(3) : "—"}</td>
                  <td>{s.intensity.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
