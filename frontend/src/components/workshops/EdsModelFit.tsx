// EDS model-fit section (PLAN_SPECTRAL_QUANT #4/#5/#7/#8/#11): fit the
// Kramers bremsstrahlung continuum, or deconvolve overlapping
// characteristic peaks with a constrained multi-Gaussian model and
// quantify the net areas — Cliff-Lorimer (k-factors) or ζ-factor
// (Watanabe: composition + mass-thickness from the electron dose).
// Optional escape/sum artifact pre-pass draws markers on the spectrum;
// the result table exports to CSV. Renders the summed spectrum + fitted
// curves straight from the endpoint response.

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  edsContinuum,
  edsPeakfit,
  edsRecalibrate,
  edsZeta,
  type EdsArtifactMark,
  type EdsContinuumResult,
  type EdsPeakfitResult,
  type EdsRecalibrateResult,
  type EdsZetaQuant,
  type EdsZetaResult,
} from "../../lib/api";
import { csvBaseName, downloadCsv } from "../../lib/eelsQuantCsv";
import { edsModelFitToCsv } from "../../lib/edsQuantCsv";
import { formatPlusMinus } from "../../lib/formatUncertainty";
import { useViewer } from "../../store/viewer";
import { EDS_PALETTE } from "./EdsComposite";

type Background = "none" | "linear" | "bremsstrahlung";
type QuantMethod = "cl" | "zeta";

const MARK_COLOR: Record<EdsArtifactMark["status"], string> = {
  measured: "#a3e635", // fitted freely — trustworthy
  modeled: "#f59e0b", // fraction × parent — an estimate
  skipped: "#ef4444", // blocked sum peak left in the data — beware
};

/** Summed spectrum + fitted-curve overlay (continuum or model + peaks). */
function ModelFitPlot({
  cont,
  peakfit,
}: {
  cont: EdsContinuumResult | null;
  peakfit: EdsPeakfitResult | EdsZetaResult | null;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    plotRef.current?.destroy();
    plotRef.current = null;

    const base = cont ?? peakfit;
    if (!base) return;

    const series: uPlot.Series[] = [
      { label: "E (keV)" },
      { label: "spectrum", stroke: "#9ca3af", width: 1, points: { show: false } },
    ];
    const data: number[][] = [base.energy, base.spectrum];

    if (cont) {
      series.push({ label: "continuum", stroke: "#d97706", width: 1.5, points: { show: false } });
      data.push(cont.continuum);
    }
    if (peakfit) {
      series.push({ label: "model", stroke: "#22d3ee", width: 1.5, dash: [4, 2], points: { show: false } });
      data.push(peakfit.model);
      peakfit.elements.forEach((el, i) => {
        if (!el.curve) return;
        series.push({
          label: el.symbol,
          stroke: EDS_PALETTE[i % EDS_PALETTE.length],
          width: 1,
          points: { show: false },
        });
        data.push(el.curve);
      });
    }
    const marks = peakfit?.artifacts ?? [];

    plotRef.current = new uPlot(
      {
        width: host.clientWidth || 300,
        height: 180,
        scales: { x: { time: false } }, // x is keV energy, not a timestamp
        series,
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
        ],
        legend: { show: true },
        cursor: { y: false },
        hooks: {
          draw: [
            (u) => {
              // artifact markers: dashed verticals at predicted energies,
              // coloured by how the artifact was handled (#8)
              if (marks.length === 0) return;
              const ctx = u.ctx;
              ctx.save();
              ctx.setLineDash([3, 3]);
              ctx.lineWidth = 1;
              ctx.font = "9px sans-serif";
              ctx.textAlign = "center";
              marks.forEach((m, i) => {
                const x = u.valToPos(m.energy_kev, "x", true);
                if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) return;
                ctx.strokeStyle = MARK_COLOR[m.status];
                ctx.fillStyle = MARK_COLOR[m.status];
                ctx.beginPath();
                ctx.moveTo(x, u.bbox.top);
                ctx.lineTo(x, u.bbox.top + u.bbox.height);
                ctx.stroke();
                // stagger labels on two rows so neighbours stay legible
                ctx.fillText(m.label, x, u.bbox.top + 10 + (i % 2) * 10);
              });
              ctx.restore();
            },
          ],
        },
      },
      data as uPlot.AlignedData,
      host,
    );
    const ro = new ResizeObserver(() => {
      if (plotRef.current && host.clientWidth > 0) {
        plotRef.current.setSize({ width: host.clientWidth, height: 180 });
      }
    });
    ro.observe(host);
    return () => {
      ro.disconnect();
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [cont, peakfit]);

  return <div ref={hostRef} className="fvd-ws-plot" />;
}

export default function EdsModelFit({
  activeId,
  elements,
}: {
  activeId: string | null;
  elements: string;
}) {
  const setStatus = useViewer((s) => s.setStatus);
  const imageName = useViewer((s) =>
    activeId ? s.images[activeId]?.name : undefined,
  );

  const [e0, setE0] = useState("200");
  const [background, setBackground] = useState<Background>("bremsstrahlung");
  const [quantify, setQuantify] = useState(true);
  const [method, setMethod] = useState<QuantMethod>("cl");
  const [zetaSi, setZetaSi] = useState("1000");
  const [probeNa, setProbeNa] = useState("1");
  const [liveS, setLiveS] = useState("100");
  const [density, setDensity] = useState("");
  const [removeArts, setRemoveArts] = useState(false);
  const [cont, setCont] = useState<EdsContinuumResult | null>(null);
  const [peakfit, setPeakfit] = useState<EdsPeakfitResult | EdsZetaResult | null>(null);
  const [recal, setRecal] = useState<EdsRecalibrateResult | null>(null);
  const [busy, setBusy] = useState<"" | "continuum" | "peakfit" | "recal">("");

  const els = elements
    .split(",")
    .map((e) => e.trim())
    .filter(Boolean);
  const e0Kev = Number(e0) || 200;

  const runContinuum = () => {
    if (!activeId) return;
    setBusy("continuum");
    setPeakfit(null);
    edsContinuum(activeId, e0Kev, { excludeLines: els, fitAbsorption: true })
      .then((r) => {
        setCont(r);
        setStatus(
          `EDS continuum · χ²ᵣ ${r.reduced_chi2.toExponential(2)} · ` +
            `amp ${r.amp.toPrecision(3)}${r.success ? "" : " · (not converged)"}`,
        );
      })
      .catch((e: Error) => setStatus(`EDS continuum: ${e.message}`))
      .finally(() => setBusy(""));
  };

  const runPeakfit = () => {
    if (!activeId) return;
    if (els.length === 0) {
      setStatus("EDS peakfit: enter at least one element symbol");
      return;
    }
    setBusy("peakfit");
    setCont(null);
    const common = {
      beamKv: e0Kev,
      background,
      e0Kev: background === "bremsstrahlung" ? e0Kev : undefined,
      removeArtifacts: removeArts,
    };
    const run: Promise<EdsPeakfitResult | EdsZetaResult> =
      method === "zeta" && quantify
        ? edsZeta(activeId, els, {
            ...common,
            zetaSi: Number(zetaSi) || 1000,
            probeCurrentNa: Number(probeNa) || 1,
            liveTimeS: Number(liveS) || 100,
            densityGCm3: Number(density) > 0 ? Number(density) : undefined,
          })
        : edsPeakfit(activeId, els, { ...common, quantify });
    run
      .then((r) => {
        setPeakfit(r);
        const q = r.quant;
        const rho =
          q && "mass_thickness_ug_cm2" in q
            ? ` · ρt ${(q as EdsZetaQuant).mass_thickness_ug_cm2.toPrecision(3)} µg/cm²`
            : "";
        const ratios = r.elements
          .map((el) => `${el.symbol} ${el.net_area.toPrecision(3)}`)
          .join(" · ");
        setStatus(`EDS peakfit · χ²ᵣ ${r.reduced_chi2.toExponential(2)} · ${ratios}${rho}`);
      })
      .catch((e: Error) => setStatus(`EDS peakfit: ${e.message}`))
      .finally(() => setBusy(""));
  };

  const runRecal = () => {
    if (!activeId) return;
    if (els.length === 0) {
      setStatus("recalibrate: list elements present at known lines first");
      return;
    }
    setBusy("recal");
    edsRecalibrate(activeId, { elements: els, beamKv: e0Kev })
      .then((r) => {
        setRecal(r);
        // the energy axis changed — refresh the image meta in the store
        if (r.applied && r.image) {
          const img = r.image;
          useViewer.setState((s) => ({ images: { ...s.images, [activeId]: img } }));
        }
        const sk = r.skipped.length ? ` (skipped ${r.skipped.join(", ")})` : "";
        setStatus(
          `EDS recal · gain ${r.gain.toFixed(4)} · offset ` +
            `${r.offset.toFixed(4)} keV${sk}`,
        );
      })
      .catch((e: Error) => setStatus(`EDS recal: ${e.message}`))
      .finally(() => setBusy(""));
  };

  const exportCsv = () => {
    if (!peakfit) return;
    downloadCsv(
      `${csvBaseName(imageName)}_eds_quant.csv`,
      edsModelFitToCsv(peakfit, { imageName: imageName ?? "image" }),
    );
  };

  // quant lookup by symbol for the merged net-area + at%/wt% table
  const quant = peakfit?.quant;
  const quantIdx = (sym: string) => quant?.elements.indexOf(sym) ?? -1;
  const zetaQuant =
    quant && "mass_thickness_ug_cm2" in quant ? (quant as EdsZetaQuant) : null;

  return (
    <div>
      <div className="fvd-ws-row">
        <span className="k">E₀ (keV)</span>
        <input
          value={e0}
          style={{ width: 56 }}
          title="Beam energy — Duane–Hunt continuum cutoff and line-selection overvoltage"
          onChange={(e) => setE0(e.target.value)}
        />
        <span className="k">bg</span>
        <div className="fvd-seg">
          {(["none", "linear", "bremsstrahlung"] as const).map((b) => (
            <button
              key={b}
              className={`fvd-seg-btn${background === b ? " active" : ""}`}
              title={
                b === "bremsstrahlung"
                  ? "Kramers continuum (pure, for a stable joint fit)"
                  : b
              }
              onClick={() => setBackground(b)}
            >
              {b === "bremsstrahlung" ? "brems" : b}
            </button>
          ))}
        </div>
      </div>
      <div className="fvd-ws-row">
        <button
          className="fvd-btn"
          title="Fit the Kramers bremsstrahlung continuum through the masked element peaks (#4)"
          disabled={busy !== "" || !activeId}
          onClick={runContinuum}
        >
          {busy === "continuum" ? "Fitting…" : "Fit continuum"}
        </button>
        <button
          className="fvd-btn"
          title="Constrained multi-Gaussian deconvolution of overlapping peaks (#5)"
          disabled={busy !== "" || !activeId || els.length === 0}
          onClick={runPeakfit}
        >
          {busy === "peakfit" ? "Fitting…" : "Deconvolve peaks"}
        </button>
        <label className="k" style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <input
            type="checkbox"
            checked={quantify}
            onChange={(e) => setQuantify(e.target.checked)}
          />
          quant
        </label>
        <div className="fvd-seg">
          {(["cl", "zeta"] as const).map((m) => (
            <button
              key={m}
              className={`fvd-seg-btn${method === m ? " active" : ""}`}
              title={
                m === "zeta"
                  ? "ζ-factor (Watanabe): composition + mass-thickness from the electron dose (#7)"
                  : "Cliff-Lorimer k-factor ratios"
              }
              onClick={() => setMethod(m)}
            >
              {m === "zeta" ? "ζ" : "CL"}
            </button>
          ))}
        </div>
        <label
          className="k"
          title="Predict escape/sum peaks, measure or model them, and refit on the corrected spectrum (#8)"
          style={{ display: "flex", alignItems: "center", gap: 4 }}
        >
          <input
            type="checkbox"
            checked={removeArts}
            onChange={(e) => setRemoveArts(e.target.checked)}
          />
          artifacts
        </label>
      </div>

      {method === "zeta" && quantify && (
        <div className="fvd-ws-row">
          <span className="k" title="Absolute ζ for Si-Kα on this detector (kg/m²) — scales the built-in k-factor table via ζᵢ = kᵢ·ζ_Si">
            ζ_Si
          </span>
          <input value={zetaSi} style={{ width: 52 }} onChange={(e) => setZetaSi(e.target.value)} />
          <span className="k">I (nA)</span>
          <input value={probeNa} style={{ width: 40 }} onChange={(e) => setProbeNa(e.target.value)} />
          <span className="k">τ (s)</span>
          <input value={liveS} style={{ width: 48 }} onChange={(e) => setLiveS(e.target.value)} />
          <span className="k" title="Optional density (g/cm³) to convert mass-thickness into thickness (nm)">
            ρ (g/cc)
          </span>
          <input value={density} style={{ width: 44 }} placeholder="—" onChange={(e) => setDensity(e.target.value)} />
        </div>
      )}

      <div className="fvd-ws-row">
        <button
          className="fvd-btn"
          title="Recalibrate the energy axis from the listed elements' known lines (#9)"
          disabled={busy !== "" || !activeId || els.length === 0}
          onClick={runRecal}
        >
          {busy === "recal" ? "Recalibrating…" : "Recalibrate E-axis"}
        </button>
        {recal && (
          <span className="k" style={{ fontSize: 11 }}>
            gain {recal.gain.toFixed(4)}, offset {recal.offset.toFixed(3)} keV
          </span>
        )}
        {peakfit && (
          <button
            className="fvd-btn"
            title="Export the fit table (net areas, at%/wt% ± 1σ, ζ mass-thickness, artifact trail) as CSV (#11)"
            onClick={exportCsv}
          >
            Export CSV
          </button>
        )}
      </div>

      {(cont || peakfit) && <ModelFitPlot cont={cont} peakfit={peakfit} />}

      {zetaQuant && (
        <div className="fvd-ws-row k" style={{ fontSize: 11 }}>
          ρt {formatPlusMinus(zetaQuant.mass_thickness_ug_cm2,
            zetaQuant.mass_thickness_error_kg_m2 * 1e5, 3)}{" "}
          µg/cm²
          {zetaQuant.thickness_nm != null &&
            ` · t ${zetaQuant.thickness_nm.toPrecision(3)} nm`}
          {` · dose ${zetaQuant.dose_electrons.toExponential(2)} e⁻`}
        </div>
      )}

      {peakfit && (
        <table className="fvd-ws-table">
          <thead>
            <tr>
              <th>El</th>
              <th>Line</th>
              <th>net area ± 1σ</th>
              {quant && <th>at% ± 1σ</th>}
              {quant && <th>wt% ± 1σ</th>}
            </tr>
          </thead>
          <tbody>
            {peakfit.elements.map((el) => {
              const qi = quantIdx(el.symbol);
              return (
                <tr key={el.symbol}>
                  <td>{el.symbol}</td>
                  <td>{el.line || "—"}</td>
                  <td>
                    {Number.isFinite(el.net_area)
                      ? `${el.net_area.toPrecision(3)} ± ${el.net_area_error.toPrecision(2)}`
                      : "—"}
                  </td>
                  {quant && (
                    <td>
                      {qi >= 0
                        ? formatPlusMinus(
                            quant.atomic_percent[qi],
                            quant.atomic_percent_error?.[qi] ?? 0,
                            2,
                          )
                        : "—"}
                    </td>
                  )}
                  {quant && (
                    <td>
                      {qi >= 0
                        ? formatPlusMinus(
                            quant.weight_percent[qi],
                            quant.weight_percent_error?.[qi] ?? 0,
                            2,
                          )
                        : "—"}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
