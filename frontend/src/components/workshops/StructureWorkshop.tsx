// Structure workshop (plan #28 tail): first dedicated UI for the five
// structure endpoints — atom columns (overlay + lattice vectors),
// template match (ROI-as-template, match overlay), CTF (fit plot),
// lattice spacing (two clicks on an FFT) and tile stitching.

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";
import { useShallow } from "zustand/react/shallow";

import {
  analyzeAtoms,
  analyzeCtf,
  analyzeGpa,
  analyzeGrainsAsync,
  analyzeLattice,
  analyzeParticles,
  analyzeStitch,
  analyzeTemplate,
  fetchData16,
  imageFft,
  renderUrl,
  runJob,
  type AtomsResult,
  type CtfResult,
  type GrainMethod,
  type GrainParams,
  type GrainResult,
  type Raster16,
} from "../../lib/api";
import { useViewer, type Measure } from "../../store/viewer";
import { useResults } from "../overlays/ResultsWindow";

const VIEW_W = 300;
const MODES = [
  "Atoms",
  "Particles",
  "Grains",
  "Template",
  "GPA",
  "CTF",
  "Lattice",
  "Stitch",
] as const;
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
          {mode === "Particles" && activeId && (
            <ParticlesMode id={activeId} />
          )}
          {mode === "Grains" && activeId && <GrainsMode id={activeId} />}
          {mode === "Template" && activeId && (
            <TemplateMode id={activeId} />
          )}
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
      <div
        className="fvd-ws-pattern"
        style={{ width: VIEW_W, height: viewH }}
      >
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
            >
              {p}
            </button>
          ))}
        </div>
        <span className="k">min px</span>
        <input value={minArea} style={{ width: 40 }}
               onChange={(e) => setMinArea(e.target.value)} />
        <button className="fvd-btn primary" onClick={count} disabled={busy}>
          {busy ? "Counting…" : "Count"}
        </button>
      </div>
    </>
  );
}

// ── Grains (interactive identification window) ───────────────────────

// method → the one tuning knob it exposes; higher coarseness / merge / K
// is fewer, larger grains. Classic k-means is the ported MATLAB path.
const GRAIN_METHODS: { value: GrainMethod; label: string; knob: string }[] = [
  { value: "gradient", label: "Gradient — visible boundaries", knob: "coarseness" },
  { value: "rag", label: "Superpixel — diffraction contrast", knob: "merge thr" },
  { value: "orientation", label: "Orientation — atomic-res", knob: "coarseness" },
  { value: "kmeans", label: "Classic k-means", knob: "classes" },
];

function GrainsMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const [method, setMethod] = useState<GrainMethod>("gradient");
  const [k, setK] = useState("3");
  const [coarseness, setCoarseness] = useState("0.05");
  const [mergeThr, setMergeThr] = useState("0.08");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [labelsId, setLabelsId] = useState<string | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => {
    setLabelsId(null);
    setNote("");
  }, [id]);

  const knob = GRAIN_METHODS.find((m) => m.value === method)!.knob;
  const knobValue = method === "kmeans" ? k : method === "rag" ? mergeThr : coarseness;
  const setKnob =
    method === "kmeans" ? setK : method === "rag" ? setMergeThr : setCoarseness;

  const run = () => {
    setBusy(true);
    setProgress("starting…");
    const params: GrainParams =
      method === "kmeans"
        ? { method, k: Number(k) || 3 }
        : method === "rag"
          ? { method, merge_threshold: Number(mergeThr) || 0.08 }
          : { method, granularity: Number(coarseness) || 0.05 };
    runJob<GrainResult>(
      () => analyzeGrainsAsync(id, params),
      (f, msg) => setProgress(`${Math.round(f * 100)}% ${msg}`),
    )
      .then((r) => {
        ingestDerived([r.labels]);
        setLabelsId(r.labels.id);
        const bits = [
          `${r.n_grains} grains`,
          `mean ⌀ ${r.mean_diameter_px.toFixed(1)} px`,
        ];
        if (r.astm_grain_size != null)
          bits.push(`ASTM G ${r.astm_grain_size.toFixed(1)}`);
        bits.push(`${r.n_triple_junctions} junctions`);
        setNote(bits.join(" · "));
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
        <Preview id={id} markers={[]} color="var(--capture)" />
      )}
      <div className="fvd-ws-row">
        <span className="k">method</span>
        <select
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
      <div className="fvd-ws-row">
        <span className="k">{knob}</span>
        <input
          value={knobValue}
          style={{ width: 44 }}
          onChange={(e) => setKnob(e.target.value)}
        />
        <button className="fvd-btn primary" onClick={run} disabled={busy}>
          {busy ? progress || "Segmenting…" : "Identify grains"}
        </button>
      </div>
      {note && <div className="fvd-ws-note">{note}</div>}
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
          setStatus(`GPA: ${r.maps.length} strain maps registered`);
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
          {fmtMean(mean["exy"])}
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
