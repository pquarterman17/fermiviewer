// Result-vs-parameter plot for the sample comparison panel (W4 item 24):
// one point per sample, its aggregated mean on the y-axis, the chosen
// parameter on the x-axis, with a vertical +/-1 std error bar — "area vs
// anneal temperature, with error bars" is the literal artifact this draws.
// Reuses the uPlot + PlotContextSurface (copy/save PNG, right-click menu)
// pattern already established by components/workshops/LayersDepthPlot.tsx;
// the error bars are the one thing uPlot doesn't draw natively, added via a
// `hooks.draw` overlay exactly like LayersDepthPlot's interface markers.

import { useEffect, useRef } from "react";
import uPlot from "uplot";

import type { SampleCompareRow } from "../../lib/projectCompare";
import PlotContextSurface from "./PlotContextSurface";

export default function ResultVsParamPlot({
  rows,
  paramName,
  resultUnit,
}: {
  rows: SampleCompareRow[];
  paramName: string;
  resultUnit: string | null;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || rows.length === 0) return;
    plotRef.current?.destroy();

    const accent =
      getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() ||
      "#a78bfa";
    const xs = rows.map((r) => r.paramValue);
    const ys = rows.map((r) => r.mean);
    const stds = rows.map((r) => r.std);
    const resultLabel = resultUnit ? `area (${resultUnit}²)` : "area";

    plotRef.current = new uPlot(
      {
        width: host.clientWidth || 300,
        height: 200,
        scales: { x: { time: false } },
        series: [
          { label: paramName },
          {
            label: resultLabel,
            stroke: accent,
            width: 0,
            points: { show: true, size: 7, fill: accent, stroke: accent },
          },
        ],
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" }, label: paramName },
          {
            stroke: "#888",
            grid: { stroke: "rgba(128,128,128,0.15)" },
            label: resultLabel,
          },
        ],
        legend: { show: false },
        cursor: { y: false },
        hooks: {
          draw: [
            (u) => {
              const ctx = u.ctx;
              ctx.save();
              ctx.strokeStyle = accent;
              ctx.lineWidth = 1.5;
              const capHalf = 4;
              for (let i = 0; i < rows.length; i++) {
                const std = stds[i];
                if (!Number.isFinite(std) || std <= 0) continue;
                const x = u.valToPos(xs[i], "x", true);
                const yTop = u.valToPos(ys[i] + std, "y", true);
                const yBot = u.valToPos(ys[i] - std, "y", true);
                ctx.beginPath();
                ctx.moveTo(x, yTop);
                ctx.lineTo(x, yBot);
                ctx.moveTo(x - capHalf, yTop);
                ctx.lineTo(x + capHalf, yTop);
                ctx.moveTo(x - capHalf, yBot);
                ctx.lineTo(x + capHalf, yBot);
                ctx.stroke();
              }
              ctx.restore();
            },
          ],
        },
      },
      [xs, ys] as uPlot.AlignedData,
      host,
    );
    const ro = new ResizeObserver(() => {
      if (plotRef.current && host.clientWidth > 0) {
        plotRef.current.setSize({ width: host.clientWidth, height: 200 });
      }
    });
    ro.observe(host);
    return () => {
      ro.disconnect();
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [rows, paramName, resultUnit]);

  return (
    <PlotContextSurface
      ref={hostRef}
      plotRef={plotRef}
      label="Sample comparison"
      filename="sample_comparison.png"
      className="fvd-ws-plot"
    />
  );
}
