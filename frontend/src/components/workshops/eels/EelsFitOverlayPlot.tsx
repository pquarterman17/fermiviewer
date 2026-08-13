// Spectrum-plot overlay for the EELS "Quantify" / "Model fit" tabs: raw
// spectrum + window-integration fit (background/signal) and/or the
// simultaneous model fit (total model, power-law bg, per-edge curves, and
// its ±1σ confidence band, ANALYSIS_PRESENTATION_PLAN #3). Extracted from
// EelsWorkshop.tsx so the plot-building logic is directly testable off
// fixture props — the same split-out-the-plot pattern as
// eds/EdsModelFitPlot.tsx and EelsFitResidualPlot.tsx. Behaviour is
// otherwise unchanged: the effect body moved verbatim.

import { useEffect, useRef } from "react";
import uPlot from "uplot";

import type {
  EelsBackgroundResult,
  EelsFitResult,
  Spectrum,
} from "../../../lib/api";
import { sigmaBand } from "../../../lib/charts/sigmaBand";
import PlotContextSurface from "../../plots/PlotContextSurface";
import { KNOWN_EDGES } from "./eelsEdges";

export default function EelsFitOverlayPlot({
  spectrum,
  fit,
  fitResult,
  showEdges,
  elementFilter,
}: {
  spectrum: Spectrum;
  fit: EelsBackgroundResult | null;
  fitResult: EelsFitResult | null;
  showEdges: boolean;
  elementFilter: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    plotRef.current?.destroy();
    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue("--accent").trim() || "#a78bfa";
    const series: uPlot.Series[] = [
      {},
      { label: "spectrum", stroke: "#8888aa", width: 1 },
    ];
    const data: uPlot.AlignedData = [spectrum.energy, spectrum.counts];
    const bands: uPlot.Band[] = [];
    if (
      fit &&
      fit.background.length === spectrum.energy.length &&
      fit.signal.length === spectrum.energy.length
    ) {
      series.push({ label: "background", stroke: "#d97706", width: 1 });
      series.push({ label: "signal", stroke: accent, width: 1.5 });
      (data as unknown as number[][]).push(fit.background, fit.signal);
    }
    // model-fit overlay (#2): total model + power-law bg + per-edge components,
    // shown on the same energy axis as the summed spectrum
    if (fitResult && fitResult.energy.length === spectrum.energy.length) {
      series.push({ label: "model", stroke: accent, width: 1.5, dash: [4, 2] });
      series.push({
        label: "bg (fit)",
        stroke: "#d97706",
        width: 1,
        dash: [2, 2],
      });
      (data as unknown as number[][]).push(
        fitResult.model,
        fitResult.background,
      );
      const palette = ["#22d3ee", "#f472b6", "#fbbf24", "#34d399", "#c084fc"];
      fitResult.edges.forEach((ed, k) => {
        series.push({
          label: ed.element,
          stroke: palette[k % palette.length],
          width: 1,
        });
        (data as unknown as number[][]).push(ed.curve);
      });
      // model-confidence band (#3): shaded in the model line's own colour,
      // appended AFTER every main line (incl. the per-edge curves) so
      // nothing else's series index shifts.
      if (fitResult.model_sigma) {
        const hiIdx = series.length;
        const loIdx = hiIdx + 1;
        const cfg = sigmaBand(
          fitResult.model, fitResult.model_sigma, accent, hiIdx, loIdx,
          { label: "model ±1σ" },
        );
        series.push(...cfg.series);
        (data as unknown as number[][]).push(
          ...(cfg.data as unknown as number[][]),
        );
        bands.push(cfg.band);
      }
    }
    plotRef.current = new uPlot(
      {
        width: host.clientWidth,
        height: 180,
        scales: { x: { time: false } }, // x is eV energy-loss, not a timestamp
        series,
        bands,
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
        ],
        legend: { show: false },
        cursor: { y: false },
        hooks: {
          draw: [
            (u) => {
              if (!showEdges) return;
              // edge-ID overlay: vertical markers at known onsets
              const ctx = u.ctx;
              const sc = u.scales["x"];
              const lo = sc?.min ?? 0;
              const hi = sc?.max ?? 0;
              ctx.save();
              ctx.strokeStyle = "rgba(244, 63, 94, 0.55)";
              ctx.fillStyle = "rgba(244, 63, 94, 0.9)";
              ctx.font = "10px monospace";
              const efLower = elementFilter.toLowerCase();
              for (const [name, ev] of KNOWN_EDGES) {
                if (efLower && !name.toLowerCase().startsWith(efLower))
                  continue;
                if (ev < lo || ev > hi) continue;
                const x = u.valToPos(ev, "x", true);
                ctx.beginPath();
                ctx.moveTo(x, u.bbox.top);
                ctx.lineTo(x, u.bbox.top + u.bbox.height);
                ctx.stroke();
                ctx.fillText(name, x + 2, u.bbox.top + 10);
              }
              ctx.restore();
            },
          ],
        },
      },
      data,
      host,
    );
    return () => {
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [spectrum, fit, fitResult, showEdges, elementFilter]);

  return (
    <PlotContextSurface
      ref={hostRef}
      plotRef={plotRef}
      label="EELS spectrum"
      filename="eels-spectrum.png"
      className="fvd-ws-plot"
    />
  );
}
