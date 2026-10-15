import { useEffect, useRef } from "react";
import uPlot from "uplot";

import type { ForceAnalysis, ForceSettings, ForceTrace } from "../../lib/api";
import PlotContextSurface from "../plots/PlotContextSurface";

export type ForceAxis = "z" | "separation";

const SERIES: { key: "approach" | "retract" | "fit"; label: string; color: string }[] = [
  { key: "approach", label: "approach", color: "" },        // accent
  { key: "retract", label: "retract", color: "#e07b39" },
  { key: "fit", label: "fit", color: "#2a9d8f" },
];

/** Traces sorted along x (uPlot.join wants ascending x per table). */
function sorted(trace: ForceTrace, axis: ForceAxis): [number[], number[]] {
  const x = trace[axis];
  const order = x.map((_, i) => i).sort((a, b) => x[a] - x[b]);
  return [order.map((i) => x[i]), order.map((i) => trace.force[i])];
}

export function forceTables(result: ForceAnalysis, axis: ForceAxis) {
  const traces = { ...result.plot, fit: result.fit ?? undefined };
  return SERIES.filter((s) => traces[s.key]).map((s) => ({
    ...s,
    table: sorted(traces[s.key] as ForceTrace, axis),
  }));
}

export default function ForceCurvePlot({
  result, axis, settings,
}: {
  result: ForceAnalysis;
  axis: ForceAxis;
  settings: ForceSettings;
}) {
  const host = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => {
    const element = host.current;
    const parts = forceTables(result, axis);
    if (!element || !parts.length) return;
    const accent =
      getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() ||
      "#7c5ce7";
    const data = uPlot.join(parts.map((p) => p.table as uPlot.AlignedData));
    const approach = result.plot.approach;
    const baseline = approach && approach.z.length > 1 && axis === "z" ? (() => {
      const start = Math.min(approach.z.length - 1, Math.floor(approach.z.length * settings.baseline_from));
      const end = Math.min(approach.z.length - 1, Math.floor(approach.z.length * settings.baseline_to));
      return [Math.min(approach.z[start], approach.z[end]), Math.max(approach.z[start], approach.z[end])] as const;
    })() : null;
    const contact = axis === "z" ? result.values.contact_z : 0;
    plotRef.current = new uPlot(
      {
        width: element.clientWidth || 600,
        height: 240,
        scales: { x: { time: false } },
        series: [
          {},
          ...parts.map((p) => ({
            label: p.label,
            stroke: p.color || accent,
            width: p.key === "fit" ? 2 : 1.25,
            dash: p.key === "fit" ? [6, 4] : undefined,
            spanGaps: true,
          })),
        ],
        axes: [
          {
            label: axis === "z" ? "Z (nm, toward the sample →)" : "tip–sample separation (nm)",
            stroke: "#888",
          },
          { label: "force (nN)", stroke: "#888" },
        ],
        legend: { show: true },
        cursor: { y: false },
        hooks: {
          draw: [(plot) => {
            const { ctx, bbox } = plot;
            ctx.save();
            if (baseline) {
              const left = plot.valToPos(baseline[0], "x", true);
              const right = plot.valToPos(baseline[1], "x", true);
              ctx.fillStyle = "rgba(120, 130, 150, 0.14)";
              ctx.fillRect(Math.min(left, right), bbox.top, Math.abs(right - left), bbox.height);
            }
            if (contact !== null && Number.isFinite(contact)) {
              const x = plot.valToPos(contact, "x", true);
              ctx.strokeStyle = "#d95f59";
              ctx.lineWidth = 1.5;
              ctx.setLineDash([5, 4]);
              ctx.beginPath();
              ctx.moveTo(x, bbox.top);
              ctx.lineTo(x, bbox.top + bbox.height);
              ctx.stroke();
            }
            ctx.restore();
          }],
        },
      },
      data,
      element,
    );
    return () => {
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [result, axis, settings.baseline_from, settings.baseline_to]);

  return (
    <PlotContextSurface
      ref={host}
      plotRef={plotRef}
      label="Force curve"
      filename="force-curve.png"
      className="fvd-ws-plot"
    />
  );
}
