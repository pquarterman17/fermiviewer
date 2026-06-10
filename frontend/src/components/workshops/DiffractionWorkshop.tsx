// Diffraction workshop (handoff §4 Inspector · Diffraction): spot
// detection overlaid on the pattern, camera geometry, phase indexing.

import { useEffect, useRef, useState } from "react";

import {
  analyzeDiffractionSimulate,
  diffractionDetect,
  diffractionIndex,
  listDiffractionPhases,
  renderUrl,
  type PhaseCandidate,
  type PhaseInfo,
  type SimulateResult,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";

const VIEW_W = 300;

/** Cluster detected-spot radii (about the pattern centre) into rings:
 *  radii within 3 px merge; each cluster's mean becomes a ring. */
function ringRadii(
  spots: [number, number][],
  nat: { w: number; h: number },
): number[] {
  const cx = nat.w / 2 + 0.5;
  const cy = nat.h / 2 + 0.5;
  const radii = spots
    .map(([r, c]) => Math.hypot(c - cx, r - cy))
    .filter((r) => r > 2)
    .sort((a, b) => a - b);
  const rings: number[][] = [];
  for (const r of radii) {
    const last = rings[rings.length - 1];
    if (last && r - last[last.length - 1] < 3) last.push(r);
    else rings.push([r]);
  }
  return rings.map((g) => g.reduce((s, v) => s + v, 0) / g.length);
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
  const [candidates, setCandidates] = useState<PhaseCandidate[]>([]);
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
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(
    null,
  );

  const isImage = meta?.kind === "image";

  useEffect(() => {
    setSpots([]);
    setCandidates([]);
    setNatural(null);
  }, [activeId]);

  // Load the phase list once (static catalog from the backend)
  useEffect(() => {
    listDiffractionPhases()
      .then((list) => {
        setPhases(list);
        if (list.length > 0) setSimPhase(list[0].name);
      })
      .catch(() => undefined);
  }, []);

  const detect = () => {
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
  };

  const index = () => {
    if (!activeId || spots.length === 0) return;
    setBusy(true);
    diffractionIndex(activeId, spots, {
      pixelSizeMm: Number(pixelSize) || 1.0,
      cameraLengthMm: cameraLen ? Number(cameraLen) : undefined,
      accKv: Number(accKv) || 200,
    })
      .then((r) => setCandidates(r.candidates))
      .catch((e: Error) => setStatus(`index: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const simulate = () => {
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
  };

  if (!isImage) {
    return (
      <div className="fvd-ws-empty">
        Select a 2D diffraction pattern (or run FFT on a lattice image).
      </div>
    );
  }

  const scale = natural ? VIEW_W / natural.w : 0;
  const viewH = natural ? natural.h * scale : VIEW_W;

  // A7: manual click — add spot on click, remove if within 6px of existing
  const HIT_R = 6;
  const onPatternClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!clickMode || !natural || scale === 0) return;
    const r = e.currentTarget.getBoundingClientRect();
    const sx = e.clientX - r.left;
    const sy = e.clientY - r.top;
    // convert display px → 1-based (row, col) image coords
    const col = sx / scale + 0.5;
    const row = sy / scale + 0.5;
    const hit = spots.findIndex(([sr, sc]) => {
      const dx = (sc - col) * scale;
      const dy = (sr - row) * scale;
      return Math.hypot(dx, dy) <= HIT_R;
    });
    if (hit >= 0) {
      // remove existing spot
      setSpots(spots.filter((_, i) => i !== hit));
    } else {
      setSpots([...spots, [row, col]]);
    }
  };

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
            onClick={onPatternClick}
            style={{ cursor: clickMode ? "crosshair" : "default" }}
          >
            {spots.map(([r, c], i) => (
              <circle
                key={i}
                // backend spots are 1-based (row, col)
                cx={(c - 0.5) * scale}
                cy={(r - 0.5) * scale}
                r={clickMode ? 6 : 4}
                fill={clickMode ? "rgba(var(--capture-rgb,53,224,194),0.2)" : "none"}
                stroke="var(--capture)"
                strokeWidth={1.5}
                style={{ cursor: clickMode ? "pointer" : "default" }}
              />
            ))}
            {rings &&
              ringRadii(spots, natural).map((rr, i) => (
                <circle
                  key={`ring-${i}`}
                  cx={((natural.w / 2 + 0.5) - 0.5) * scale}
                  cy={((natural.h / 2 + 0.5) - 0.5) * scale}
                  r={rr * scale}
                  fill="none"
                  stroke="#f59e0b"
                  strokeWidth={1}
                  strokeDasharray="4 3"
                />
              ))}
          </svg>
        )}
      </div>

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
      <div className="fvd-ws-row">
        <button
          className={`fvd-btn${clickMode ? " active" : ""}`}
          onClick={() => setClickMode((v) => !v)}
          title="Click spots manually on the pattern preview (A7)"
        >
          {clickMode ? "Done Clicking" : "Click Spots"}
        </button>
        {clickMode && (
          <span className="fvd-ws-hint">
            Click to add · click existing to remove
          </span>
        )}
        {spots.length > 0 && !clickMode && (
          <span className="fvd-ws-hint">{spots.length} spots</span>
        )}
      </div>
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

      {candidates.length > 0 && (
        <table className="fvd-ws-table">
          <thead>
            <tr>
              <th>Phase</th>
              <th>Zone</th>
              <th>Matched</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => (
              <tr key={`${c.phase}-${c.zone_axis.join("")}`}>
                <td title={c.formula}>{c.phase}</td>
                <td>[{c.zone_axis.join(" ")}]</td>
                <td>{c.n_matched}</td>
                <td>{c.score.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
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
