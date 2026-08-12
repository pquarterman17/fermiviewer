// Residual trace (observed − model) under the EELS model-fit overlay
// (ANALYSIS_PRESENTATION_PLAN.md #2 / audit R4). A separate, small uPlot
// instance rather than a second y-scale bolted onto EelsWorkshop's fit
// overlay plot — residuals sit near zero while the spectrum itself spans
// orders of magnitude, so sharing one y-axis would flatten the residual
// trace to an invisible line at that scale. Built the same way the rest
// of this workshop builds its bespoke plots: a `new uPlot(...)` in a
// build effect, torn down on unmount/re-run.

import { useEffect, useRef } from "react";
import uPlot from "uplot";

import type { EelsFitResult } from "../../../lib/api";
import { residual } from "../../../lib/spectrum/fitQuality";
import PlotContextSurface from "../../plots/PlotContextSurface";

const HEIGHT = 80;

export default function EelsFitResidualPlot({
  result,
}: {
  result: EelsFitResult;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    plotRef.current?.destroy();
    plotRef.current = null;
    if (
      result.energy.length === 0 ||
      result.energy.length !== result.spectrum.length ||
      result.energy.length !== result.model.length
    ) {
      return;
    }
    const resid = residual(result.spectrum, result.model);
    const u = new uPlot(
      {
        width: host.clientWidth || 300,
        height: HEIGHT,
        scales: { x: { time: false } }, // x is eV energy-loss, not a timestamp
        series: [{}, { label: "residual", stroke: "#f87171", width: 1 }],
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          {
            stroke: "#888",
            grid: { stroke: "rgba(128,128,128,0.15)" },
            size: 48,
          },
        ],
        legend: { show: false },
        cursor: { y: false },
        hooks: {
          draw: [
            (u2) => {
              // zero baseline — the reference a "good" residual hugs
              const ctx = u2.ctx;
              const y0 = u2.valToPos(0, "y", true);
              ctx.save();
              ctx.strokeStyle = "rgba(148,163,184,0.6)";
              ctx.setLineDash([3, 3]);
              ctx.beginPath();
              ctx.moveTo(u2.bbox.left, y0);
              ctx.lineTo(u2.bbox.left + u2.bbox.width, y0);
              ctx.stroke();
              ctx.restore();
            },
          ],
        },
      },
      [result.energy, resid],
      host,
    );
    plotRef.current = u;
    return () => {
      u.destroy();
      plotRef.current = null;
    };
  }, [result]);

  return (
    <PlotContextSurface
      ref={hostRef}
      plotRef={plotRef}
      label="EELS fit residual"
      filename="eels-fit-residual.png"
      className="fvd-ws-plot"
      style={{ minHeight: HEIGHT, height: HEIGHT }}
    />
  );
}
