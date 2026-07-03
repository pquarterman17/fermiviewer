// EDS model-fit section (PLAN_SPECTRAL_QUANT #4/#5): fit the Kramers
// bremsstrahlung continuum, or deconvolve overlapping characteristic peaks
// with a constrained multi-Gaussian model and optionally Cliff-Lorimer
// quantify the net areas. Renders the summed spectrum + fitted curves
// straight from the endpoint response (which carries energy/spectrum/curve).

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  edsContinuum,
  edsPeakfit,
  edsRecalibrate,
  type EdsContinuumResult,
  type EdsPeakfitResult,
  type EdsRecalibrateResult,
} from "../../lib/api";
import { formatPlusMinus } from "../../lib/formatUncertainty";
import { useViewer } from "../../store/viewer";
import { EDS_PALETTE } from "./EdsComposite";

type Background = "none" | "linear" | "bremsstrahlung";

/** Summed spectrum + fitted-curve overlay (continuum or model + peaks). */
function ModelFitPlot({
  cont,
  peakfit,
}: {
  cont: EdsContinuumResult | null;
  peakfit: EdsPeakfitResult | null;
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

  const [e0, setE0] = useState("200");
  const [background, setBackground] = useState<Background>("bremsstrahlung");
  const [quantify, setQuantify] = useState(true);
  const [cont, setCont] = useState<EdsContinuumResult | null>(null);
  const [peakfit, setPeakfit] = useState<EdsPeakfitResult | null>(null);
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
    edsPeakfit(activeId, els, {
      beamKv: e0Kev,
      background,
      e0Kev: background === "bremsstrahlung" ? e0Kev : undefined,
      quantify,
    })
      .then((r) => {
        setPeakfit(r);
        const ratios = r.elements
          .map((el) => `${el.symbol} ${el.net_area.toPrecision(3)}`)
          .join(" · ");
        setStatus(`EDS peakfit · χ²ᵣ ${r.reduced_chi2.toExponential(2)} · ${ratios}`);
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

  // quant lookup by symbol for the merged net-area + at%/wt% table
  const quant = peakfit?.quant;
  const quantIdx = (sym: string) => quant?.elements.indexOf(sym) ?? -1;

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
      </div>

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
      </div>

      {(cont || peakfit) && <ModelFitPlot cont={cont} peakfit={peakfit} />}

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
