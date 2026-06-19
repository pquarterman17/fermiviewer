// Diffraction workshop (handoff §4 Inspector · Diffraction): spot
// detection overlaid on the pattern, camera geometry, phase indexing,
// matched-phase rings (port of drawMatchedRings.m), typed-d ring overlay,
// and analysis-ROI drawing (rect / circle) to scope detect + index.

import { useCallback, useEffect, useRef, useState } from "react";

import {
  analyzeDiffractionSimulate,
  diffractionDetect,
  diffractionDetectWithRoi,
  diffractionIndex,
  listDiffractionPhases,
  renderUrl,
  type AnalysisRoi,
  type IndexResult,
  type PhaseCandidate,
  type PhaseInfo,
  type SimulateResult,
} from "../../lib/api";
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
function matchedRingSvg(
  candidate: PhaseCandidate,
  measuredR: number[],
  center: [number, number],   // 1-based (row, col)
  scale: number,
  imgW: number,
  pixelSizeMm: number,
): React.ReactNode[] {
  const cx = (center[1] - 0.5) * scale;  // 1-based col → display px
  const cy = (center[0] - 0.5) * scale;
  const nodes: React.ReactNode[] = [];
  const { matched_hkl, matched_d } = candidate;
  if (!matched_d || matched_d.length === 0 || measuredR.length === 0) return [];

  // Compute the measured d-spacing for each spot from its radius:
  //   d_meas[i] = W * pixelSize / R[i]  (FFT mode, verbatim indexDiffraction.m)
  // Then match each matched_d[k] to the nearest unused spot, greedy in spot order.
  const dPerSpot = measuredR.map((R) =>
    R > 0 ? (imgW * pixelSizeMm) / R : Infinity,
  );
  const used = new Set<number>();

  for (let k = 0; k < matched_d.length; k++) {
    const dm = matched_d[k];
    let bestIdx = -1;
    let bestFrac = Infinity;
    for (let i = 0; i < dPerSpot.length; i++) {
      if (used.has(i)) continue;
      const frac = Math.abs(dPerSpot[i] - dm) / dm;
      if (frac < bestFrac) { bestFrac = frac; bestIdx = i; }
    }
    if (bestIdx < 0) continue;
    used.add(bestIdx);

    const R = measuredR[bestIdx] * scale;
    const hkl = matched_hkl[k] ?? [0, 0, 0];
    nodes.push(
      <g key={`mring-${k}`}>
        <circle cx={cx} cy={cy} r={R} fill="none" stroke="#22c55e" strokeWidth={1} />
        <text
          x={cx + R * 1.05}
          y={cy}
          fill="#22c55e"
          fontSize={9}
          dominantBaseline="middle"
        >
          ({hkl.join("")})
        </text>
      </g>,
    );
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
  const [busy, setBusy] = useState(false);
  // A8 simulate
  const [phases, setPhases] = useState<PhaseInfo[]>([]);
  const [simPhase, setSimPhase] = useState("");
  const [simZa, setSimZa] = useState("0 0 1");
  const [simResult, setSimResult] = useState<SimulateResult | null>(null);
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
  }, [simPhase, simZa, activeId, setStatus]);

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
    rings && indexResult && candidates.length > 0 && natural
      ? matchedRingSvg(
          candidates[selectedCandIdx] ?? candidates[0],
          indexResult.measured_r,
          indexResult.center as [number, number],
          scale,
          natural.w,
          Number(pixelSize) || 1.0,
        )
      : [];

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
        <button className="fvd-btn" onClick={detect} disabled={busy}>
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
        <div className="fvd-ws-note" style={{ fontSize: 10 }}>
          Click a row to select · enable Rings to overlay matched d-spacings
        </div>
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
              {p.name}
            </option>
          ))}
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
