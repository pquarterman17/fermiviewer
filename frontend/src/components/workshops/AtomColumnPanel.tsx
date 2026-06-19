// Atom-column workshop panel — parity with
// fermi-viewer/+fermiViewer/+atomcolumns/openAtomColumnWorkshop.m
//
// Controls (matching MATLAB layout order):
//   Polarity toggle (bright / dark)
//   Pre-smooth σ, threshold, min-separation, fit-window radius
//   Detect + Fit button
//   Sublattice count (1–4) selector
//   Strain (PPA) button  →  εxx / εyy / εxy / rotation per column
//   Overlay selector: Markers / Sublattice / εxx / εyy / εxy / Rotation
//   R² / strain-median readout
//   Column CSV export / overlay PNG export

import { useEffect, useState } from "react";

import {
  analyzeAtoms,
  analyzeAtomsStrain,
  atomsExportCsv,
  renderUrl,
  type AtomsResult,
  type PpaStrain,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";

// ── colour palette for sublattices (matches MATLAB subColors) ────────
const SUB_COLORS = ["#33%s", "#ff8c26", "#4dd966", "#e64ccc"]
  .map((_, i) =>
    ["#3399ff", "#ff8c26", "#4dd966", "#e64ccc"][i],
  );

const VIEW_W = 300;

type OverlayKey = "markers" | "sublattice" | "exx" | "eyy" | "exy" | "rotation";
const OVERLAY_LABELS: { key: OverlayKey; label: string }[] = [
  { key: "markers", label: "Markers" },
  { key: "sublattice", label: "Sublattice" },
  { key: "exx", label: "εxx" },
  { key: "eyy", label: "εyy" },
  { key: "exy", label: "εxy" },
  { key: "rotation", label: "Rotation" },
];

// ── diverging blue-white-red colormap (matches MATLAB divergingMap) ──
function divergingColor(v: number, vmax: number): string {
  if (!isFinite(v) || vmax <= 0) return "rgba(128,128,128,0.6)";
  const t = Math.max(-1, Math.min(1, v / vmax)); // [-1, 1]
  if (t < 0) {
    // negative → blue-white
    const f = 1 + t; // [0,1] at t=-1 → blue; 1 at t=0 → white
    const r = Math.round(f * 255);
    const g = Math.round(f * 255);
    return `rgb(${r},${g},255)`;
  } else {
    // positive → white-red
    const f = 1 - t;
    const g = Math.round(f * 255);
    const b = Math.round(f * 255);
    return `rgb(255,${g},${b})`;
  }
}

// ── 95th-percentile (no Stats Toolbox, matches MATLAB pct95) ─────────
function pct95(vals: number[]): number {
  const finite = vals.filter(isFinite);
  if (finite.length === 0) return 1;
  const sorted = [...finite].sort((a, b) => a - b);
  return sorted[Math.max(0, Math.ceil(0.95 * sorted.length) - 1)];
}

// ── overlay canvas renderer ───────────────────────────────────────────

function AtomOverlay({
  res,
  overlay,
  nat,
  scale,
  strain,
}: {
  res: AtomsResult;
  overlay: OverlayKey;
  nat: { w: number; h: number };
  scale: number;
  strain: PpaStrain | null;
}) {
  const strainVals =
    overlay === "exx" ? strain?.exx
    : overlay === "eyy" ? strain?.eyy
    : overlay === "exy" ? strain?.exy
    : overlay === "rotation" ? strain?.rotation
    : null;

  const vmax =
    strainVals
      ? pct95(strainVals.filter((v): v is number => v !== null).map(Math.abs))
      : 1;

  const viewH = nat.h * scale;

  return (
    <svg
      width={VIEW_W}
      height={viewH}
      pointerEvents="none"
      style={{ position: "absolute", top: 0, left: 0 }}
    >
      {res.positions.map(([x, y], i) => {
        let fill = "none";
        let stroke = "var(--capture, #f33)";
        let r = 3;

        if (overlay === "sublattice" && res.sublattice) {
          const label = (res.sublattice[i] ?? 1) - 1;
          fill = SUB_COLORS[Math.min(label, SUB_COLORS.length - 1)];
          stroke = "none";
          r = 4;
        } else if (strainVals) {
          const v = strainVals[i];
          fill = divergingColor(v ?? NaN, vmax);
          stroke = "none";
          r = 4;
        }

        return (
          <circle
            key={i}
            cx={(x - 0.5) * scale}
            cy={(y - 0.5) * scale}
            r={r}
            fill={fill}
            stroke={stroke}
            strokeWidth={1.2}
          />
        );
      })}
    </svg>
  );
}

// ── strain colorbar legend ────────────────────────────────────────────

function StrainLegend({ vmax }: { vmax: number }) {
  const steps = [-1, -0.5, 0, 0.5, 1];
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10 }}>
      {steps.map((t) => (
        <span key={t} style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <span
            style={{
              width: 12, height: 12, borderRadius: 2,
              background: divergingColor(t * vmax, vmax),
            }}
          />
          <span style={{ color: "var(--fg-muted)" }}>
            {(t * vmax * 100).toFixed(1)}%
          </span>
        </span>
      ))}
    </div>
  );
}

// ── main panel ────────────────────────────────────────────────────────

export default function AtomColumnPanel({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);

  // detection params
  const [sigma, setSigma] = useState("2");
  const [thresh, setThresh] = useState("0.2");
  const [minSep, setMinSep] = useState("8");
  const [winRadius, setWinRadius] = useState("6");
  const [polarity, setPolarity] = useState<"bright" | "dark">("bright");
  const [sublattices, setSublattices] = useState(1);

  // results
  const [res, setRes] = useState<AtomsResult | null>(null);
  const [strain, setStrain] = useState<PpaStrain | null>(null);
  const [overlay, setOverlay] = useState<OverlayKey>("markers");
  const [busy, setBusy] = useState(false);
  const [strainBusy, setStrainBusy] = useState(false);
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);

  useEffect(() => {
    setRes(null);
    setStrain(null);
    setOverlay("markers");
  }, [id]);

  const scale = nat ? VIEW_W / nat.w : 0;
  const viewH = nat ? nat.h * scale : VIEW_W;

  // ── detect + fit ─────────────────────────────────────────────────
  const runDetect = () => {
    setBusy(true);
    setStrain(null);
    if (overlay !== "markers" && overlay !== "sublattice") setOverlay("markers");
    analyzeAtoms(id, {
      sigma: Number(sigma) || 2,
      threshold: Number(thresh) || 0.2,
      minSeparation: Number(minSep) || 8,
      winRadius: Number(winRadius) || 6,
      polarity,
      sublattices,
    })
      .then((r) => {
        setRes(r);
        setStatus(`atoms: ${r.n_columns} columns detected`);
      })
      .catch((e: Error) => setStatus(`atoms: ${e.message}`))
      .finally(() => setBusy(false));
  };

  // ── PPA strain ───────────────────────────────────────────────────
  const runStrain = () => {
    if (!res || res.n_columns === 0) {
      setStatus("atoms: detect columns first");
      return;
    }
    setStrainBusy(true);
    const lv = res.lattice;
    analyzeAtomsStrain(res.positions, {
      refVectors: lv.valid && lv.a1 && lv.a2
        ? [lv.a1, lv.a2]
        : undefined,
      origin: undefined,
    })
      .then((st) => {
        setStrain(st);
        setOverlay("exx");
        if (st.valid) {
          const exxPct = ((st.exx_mean ?? 0) * 100).toFixed(3);
          const eyyPct = ((st.eyy_mean ?? 0) * 100).toFixed(3);
          setStatus(`atoms: strain vs avg lattice — εxx=${exxPct}%, εyy=${eyyPct}%`);
        } else {
          setStatus("atoms: PPA strain failed (need a cleaner column set)");
        }
      })
      .catch((e: Error) => setStatus(`atoms strain: ${e.message}`))
      .finally(() => setStrainBusy(false));
  };

  // ── CSV export ────────────────────────────────────────────────────
  const exportCsv = () => {
    if (!res) return;
    const csv = atomsExportCsv(
      res.positions, res.amplitude, res.sublattice,
      strain ?? undefined,
    );
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "atom_columns.csv";
    a.click();
    URL.revokeObjectURL(url);
    setStatus(`atoms: exported ${res.n_columns} columns`);
  };

  // ── overlay PNG export (canvas composite — no external deps) ────────
  const exportPng = () => {
    if (!res || !nat) return;
    const imgSrc = renderUrl(id);
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = nat.w;
      canvas.height = nat.h;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(img, 0, 0, nat.w, nat.h);
      // draw marker circles at native image resolution
      res.positions.forEach(([x, y], i) => {
        let fill = "rgba(255,50,50,0)";
        let stroke = "rgba(255,50,50,0.85)";
        if (overlay === "sublattice" && res.sublattice) {
          fill = SUB_COLORS[(res.sublattice[i] ?? 1) - 1];
          stroke = "none";
        } else if (strainValsForScale) {
          fill = divergingColor(strainValsForScale[i] ?? NaN, vmax);
          stroke = "none";
        }
        ctx.beginPath();
        ctx.arc(x - 0.5, y - 0.5, 3, 0, Math.PI * 2);
        ctx.fillStyle = fill;
        ctx.strokeStyle = stroke;
        ctx.lineWidth = 1;
        ctx.fill();
        if (stroke !== "none") ctx.stroke();
      });
      canvas.toBlob((b) => {
        if (!b) return;
        const url = URL.createObjectURL(b);
        const a = document.createElement("a");
        a.href = url;
        a.download = "atom_columns_overlay.png";
        a.click();
        URL.revokeObjectURL(url);
      });
    };
    img.src = imgSrc;
    setStatus("atoms: exporting overlay PNG…");
  };

  // ── strain readout ────────────────────────────────────────────────
  const strainValsForScale =
    overlay === "exx" ? strain?.exx
    : overlay === "eyy" ? strain?.eyy
    : overlay === "exy" ? strain?.exy
    : overlay === "rotation" ? strain?.rotation
    : null;
  const vmax = strainValsForScale
    ? pct95(strainValsForScale.filter((v): v is number => v !== null).map(Math.abs))
    : 1;

  // converged count for R² display
  const convergCount = res?.converged ? res.converged.filter(Boolean).length : null;

  return (
    <>
      {/* Image + overlay */}
      <div
        className="fvd-ws-pattern"
        style={{ position: "relative", width: VIEW_W, height: viewH }}
      >
        <img
          src={renderUrl(id)}
          alt=""
          width={VIEW_W}
          draggable={false}
          style={{ display: "block" }}
          onLoad={(e) =>
            setNat({
              w: e.currentTarget.naturalWidth,
              h: e.currentTarget.naturalHeight,
            })
          }
        />
        {res && nat && (
          <AtomOverlay
            res={res}
            overlay={overlay}
            nat={nat}
            scale={scale}
            strain={strain}
          />
        )}
      </div>

      {/* Detection params */}
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
        <span className="k">win</span>
        <input value={winRadius} style={{ width: 36 }}
               onChange={(e) => setWinRadius(e.target.value)} />
      </div>

      {/* Polarity + sublattice count */}
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
        <span className="k">sub</span>
        <select
          value={sublattices}
          style={{ width: 48 }}
          onChange={(e) => setSublattices(Number(e.target.value))}
        >
          {[1, 2, 3, 4].map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
        <button className="fvd-btn primary" onClick={runDetect} disabled={busy}>
          {busy ? "Fitting…" : "Detect + Fit"}
        </button>
      </div>

      {/* Strain button + overlay selector */}
      <div className="fvd-ws-row">
        <button
          className="fvd-btn"
          onClick={runStrain}
          disabled={strainBusy || !res || res.n_columns === 0}
        >
          {strainBusy ? "Computing…" : "Strain (PPA)"}
        </button>
        <select
          value={overlay}
          style={{ flex: 1 }}
          onChange={(e) => setOverlay(e.target.value as OverlayKey)}
        >
          {OVERLAY_LABELS.map(({ key, label }) => (
            <option
              key={key}
              value={key}
              disabled={
                (key === "sublattice" && (!res?.sublattice || sublattices < 2)) ||
                (["exx","eyy","exy","rotation"].includes(key) && !strain?.valid)
              }
            >
              {label}
            </option>
          ))}
        </select>
      </div>

      {/* Strain colorbar when a strain overlay is active */}
      {strain?.valid && strainValsForScale && (
        <div style={{ paddingLeft: 4 }}>
          <StrainLegend vmax={vmax} />
        </div>
      )}

      {/* Stats readout */}
      {res && (
        <div className="fvd-ws-note">
          {res.n_columns} columns
          {convergCount !== null && ` · ${convergCount} converged`}
          {res.lattice.valid && res.lattice.spacing !== null &&
            ` · spacing ${res.lattice.spacing.toFixed(2)} px`}
          {strain?.valid && (
            <>
              {` · εxx ${((strain.exx_mean ?? 0) * 100).toFixed(3)} %`}
              {` · εyy ${((strain.eyy_mean ?? 0) * 100).toFixed(3)} %`}
            </>
          )}
        </div>
      )}

      {/* Export buttons */}
      {res && (
        <div className="fvd-ws-row">
          <button className="fvd-btn" onClick={exportCsv}>CSV</button>
          <button className="fvd-btn" onClick={exportPng}>PNG overlay</button>
        </div>
      )}
    </>
  );
}
