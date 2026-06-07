// Structure workshop (plan #28 tail): first dedicated UI for the five
// structure endpoints — atom columns (overlay + lattice vectors),
// template match (ROI-as-template, match overlay), CTF (fit plot),
// lattice spacing (two clicks on an FFT) and tile stitching.

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  analyzeAtoms,
  analyzeCtf,
  analyzeLattice,
  analyzeStitch,
  analyzeTemplate,
  renderUrl,
  type AtomsResult,
  type CtfResult,
} from "../../lib/api";
import { useViewer, type Measure } from "../../store/viewer";

const VIEW_W = 300;
const MODES = ["Atoms", "Template", "CTF", "Lattice", "Stitch"] as const;
type Mode = (typeof MODES)[number];

const NO_MEASURES: Measure[] = [];

export default function StructureWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const [mode, setMode] = useState<Mode>("Atoms");

  const isImage = meta?.kind === "image";

  return (
    <div className="fvd-ws">
      <div className="fvd-seg">
        {MODES.map((m) => (
          <button
            key={m}
            className={`fvd-seg-btn${mode === m ? " active" : ""}`}
            onClick={() => setMode(m)}
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
          {mode === "Template" && activeId && (
            <TemplateMode id={activeId} />
          )}
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

// ── Atoms ────────────────────────────────────────────────────────────

function AtomsMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const [sigma, setSigma] = useState("2");
  const [thresh, setThresh] = useState("0.2");
  const [minSep, setMinSep] = useState("8");
  const [polarity, setPolarity] = useState<"bright" | "dark">("bright");
  const [res, setRes] = useState<AtomsResult | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => setRes(null), [id]);

  const run = () => {
    setBusy(true);
    analyzeAtoms(id, {
      sigma: Number(sigma) || 2,
      threshold: Number(thresh) || 0.2,
      minSeparation: Number(minSep) || 8,
      polarity,
    })
      .then(setRes)
      .catch((e: Error) => setStatus(`atoms: ${e.message}`))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <Preview
        id={id}
        markers={(res?.positions ?? []).map(([x, y]) => ({ x, y }))}
        color="var(--capture)"
      />
      <div className="fvd-ws-row">
        <span className="k">σ</span>
        <input value={sigma} style={{ width: 36 }}
               onChange={(e) => setSigma(e.target.value)} />
        <span className="k">thr</span>
        <input value={thresh} style={{ width: 44 }}
               onChange={(e) => setThresh(e.target.value)} />
        <span className="k">sep</span>
        <input value={minSep} style={{ width: 36 }}
               onChange={(e) => setMinSep(e.target.value)} />
      </div>
      <div className="fvd-ws-row">
        <div className="fvd-seg">
          {(["bright", "dark"] as const).map((p) => (
            <button
              key={p}
              className={`fvd-seg-btn${polarity === p ? " active" : ""}`}
              onClick={() => setPolarity(p)}
            >
              {p}
            </button>
          ))}
        </div>
        <button className="fvd-btn primary" onClick={run} disabled={busy}>
          {busy ? "Fitting…" : "Detect + fit"}
        </button>
      </div>
      {res && (
        <div className="fvd-ws-note">
          {res.n_columns} columns
          {res.lattice.valid &&
            res.lattice.spacing !== null &&
            ` · spacing ${res.lattice.spacing.toFixed(2)} px`}
          {res.converged &&
            ` · ${res.converged.filter(Boolean).length} converged`}
        </div>
      )}
    </>
  );
}

// ── Template match ───────────────────────────────────────────────────

function TemplateMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const meta = useViewer((s) => s.images[id] ?? null);
  const rois = useViewer((s) =>
    (s.measures[id] ?? NO_MEASURES).filter((m) => m.kind === "roi"),
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
        <input value={thresh} style={{ width: 44 }}
               onChange={(e) => setThresh(e.target.value)} />
        <button
          className="fvd-btn primary"
          onClick={run}
          disabled={busy || rois.length === 0}
          title={rois.length ? "" : "draw an ROI around the motif first (R)"}
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
        <input value={kv} style={{ width: 44 }}
               onChange={(e) => setKv(e.target.value)} />
        <span className="k">Cs mm</span>
        <input value={cs} style={{ width: 40 }}
               onChange={(e) => setCs(e.target.value)} />
        <span className="k">Å/px</span>
        <input value={pxA} style={{ width: 44 }}
               onChange={(e) => setPxA(e.target.value)} />
        <button className="fvd-btn primary" onClick={run} disabled={busy}>
          {busy ? "Fitting…" : "Estimate"}
        </button>
      </div>
      {res && (
        <div className="fvd-ws-note">
          Δf = {res.defocus_nm.toFixed(1)} nm · R² ={" "}
          {res.r_squared.toFixed(3)} · λ = {res.lambda_a.toFixed(4)} Å
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
            "a": `${r.a.toFixed(3)} ${r.unit}`,
            "b": `${r.b.toFixed(3)} ${r.unit}`,
            "γ": `${r.gamma_deg.toFixed(2)}°`,
            "d₁": `${r.d_spacing1.toFixed(3)} ${r.unit}`,
            "d₂": `${r.d_spacing2.toFixed(3)} ${r.unit}`,
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
            >
              {l}
            </button>
          ))}
        </div>
      </div>
      <div className="fvd-ws-row">
        <span className="k">overlap</span>
        <input value={overlap} style={{ width: 44 }}
               onChange={(e) => setOverlap(e.target.value)} />
        <button
          className="fvd-btn primary"
          onClick={run}
          disabled={busy || selected.length < 2}
        >
          {busy ? "Stitching…" : `Stitch ${selected.length} tiles`}
        </button>
      </div>
      <div className="fvd-ws-note">
        ⌘-click tiles in the filmstrip (equal sizes required), in
        acquisition order.
      </div>
    </>
  );
}
