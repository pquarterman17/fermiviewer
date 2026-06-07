// Diffraction workshop (handoff §4 Inspector · Diffraction): spot
// detection overlaid on the pattern, camera geometry, phase indexing.

import { useEffect, useRef, useState } from "react";

import {
  diffractionDetect,
  diffractionIndex,
  renderUrl,
  type PhaseCandidate,
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

  if (!isImage) {
    return (
      <div className="fvd-ws-empty">
        Select a 2D diffraction pattern (or run FFT on a lattice image).
      </div>
    );
  }

  const scale = natural ? VIEW_W / natural.w : 0;
  const viewH = natural ? natural.h * scale : VIEW_W;

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
          <svg width={VIEW_W} height={viewH}>
            {spots.map(([r, c], i) => (
              <circle
                key={i}
                // backend spots are 1-based (row, col)
                cx={(c - 0.5) * scale}
                cy={(r - 0.5) * scale}
                r={4}
                fill="none"
                stroke="var(--capture)"
                strokeWidth={1.5}
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
    </div>
  );
}
