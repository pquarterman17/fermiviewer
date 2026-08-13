// Summed spectrum + fitted-curve overlay (continuum or model + peaks) for
// EdsModelFit.tsx (PLAN_SPECTRAL_QUANT #4/#5/#8). Split out to keep
// EdsModelFit.tsx under the repo's 500-line ceiling (mirrors
// eels/EelsFitResidualPlot.tsx's split-out-the-plot pattern).

import { useEffect, useRef } from "react";
import uPlot from "uplot";

import type {
  EdsArtifactMark,
  EdsContinuumResult,
  EdsPeakfitResult,
  EdsZetaResult,
} from "../../../lib/api";
import { sigmaBand } from "../../../lib/charts/sigmaBand";
import { useElementColors } from "../../../lib/elemental/elementColors";
import PlotContextSurface from "../../plots/PlotContextSurface";

const MARK_COLOR: Record<EdsArtifactMark["status"], string> = {
  measured: "#a3e635", // fitted freely — trustworthy
  modeled: "#f59e0b", // fraction × parent — an estimate
  skipped: "#ef4444", // blocked sum peak left in the data — beware
};

const MODEL_COLOR = "#22d3ee";

export default function EdsModelFitPlot({
  cont,
  peakfit,
}: {
  cont: EdsContinuumResult | null;
  peakfit: EdsPeakfitResult | EdsZetaResult | null;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const colors = useElementColors();

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
    const data: (number | null)[][] = [base.energy, base.spectrum];
    const bands: uPlot.Band[] = [];

    if (cont) {
      series.push({ label: "continuum", stroke: "#d97706", width: 1.5, points: { show: false } });
      data.push(cont.continuum);
    }
    if (peakfit) {
      series.push({ label: "model", stroke: MODEL_COLOR, width: 1.5, dash: [4, 2], points: { show: false } });
      data.push(peakfit.model);
      peakfit.elements.forEach((el) => {
        if (!el.curve) return;
        series.push({
          label: el.symbol,
          stroke: colors(el.symbol),
          width: 1,
          points: { show: false },
        });
        data.push(el.curve);
      });
      // model-confidence band (ANALYSIS_PRESENTATION_PLAN #3): shaded in
      // the model line's own colour, appended AFTER every main line so
      // legend-click → series toggling for spectrum/model/elements is
      // unaffected by whether a band gets appended.
      if (peakfit.model_sigma) {
        const hiIdx = series.length;
        const loIdx = hiIdx + 1;
        const cfg = sigmaBand(
          peakfit.model, peakfit.model_sigma, MODEL_COLOR, hiIdx, loIdx,
          { label: "model ±1σ" },
        );
        series.push(...cfg.series);
        data.push(...cfg.data);
        bands.push(cfg.band);
      }
    }
    const marks = peakfit?.artifacts ?? [];

    plotRef.current = new uPlot(
      {
        width: host.clientWidth || 300,
        height: 180,
        scales: { x: { time: false } }, // x is keV energy, not a timestamp
        series,
        bands,
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
  }, [cont, peakfit, colors]);

  return (
    <PlotContextSurface
      ref={hostRef}
      plotRef={plotRef}
      label="EDS model fit"
      filename="eds-model-fit.png"
      className="fvd-ws-plot"
    />
  );
}
