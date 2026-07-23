// EDS spectrum plot (uPlot) with a draggable energy-window patch. Extracted
// from EdsSpectrumImage.tsx so the explorer stays under the module-size
// ceiling; the characteristic element-line / peak-label markers layer onto
// this plot's `draw` hook (see EdsSpectrumImage element navigation).

import { useEffect, useRef } from "react";
import uPlot from "uplot";

import type { Spectrum } from "../../lib/api";

export default function SpectrumPlot({
  spec,
  label,
  eLo,
  eHi,
  onDragWindow,
}: {
  spec: Spectrum;
  label: string;
  eLo: number;
  eHi: number;
  onDragWindow: (lo: number, hi: number) => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const dragRef = useRef<number | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || spec.energy.length === 0) return;
    plotRef.current?.destroy();

    const u = new uPlot(
      {
        width: host.clientWidth || 320,
        height: 160,
        title: label,
        // energy axis is keV, not a timestamp — uPlot defaults x to a time
        // scale, which renders small keV values as clock/date labels
        scales: { x: { time: false } },
        series: [
          { label: `E (${spec.units})` },
          {
            label: "Counts",
            stroke: "#333",
            width: 1,
            points: { show: false },
          },
        ],
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
        ],
        legend: { show: false },
        cursor: { y: false },
        hooks: {
          draw: [
            (u2) => {
              const ctx = u2.ctx;
              const x0 = u2.valToPos(eLo, "x");
              const x1 = u2.valToPos(eHi, "x");
              const y0 = u2.bbox.top;
              const y1 = u2.bbox.top + u2.bbox.height;
              ctx.save();
              ctx.globalAlpha = 0.15;
              ctx.fillStyle = "#3b82f6";
              ctx.fillRect(
                x0 + u2.bbox.left,
                y0,
                x1 - x0,
                y1 - y0,
              );
              ctx.globalAlpha = 1;
              ctx.strokeStyle = "#2563eb";
              ctx.lineWidth = 1.5;
              ctx.beginPath();
              ctx.moveTo(x0 + u2.bbox.left, y0);
              ctx.lineTo(x0 + u2.bbox.left, y1);
              ctx.moveTo(x1 + u2.bbox.left, y0);
              ctx.lineTo(x1 + u2.bbox.left, y1);
              ctx.stroke();
              ctx.restore();
            },
          ],
        },
      } satisfies uPlot.Options,
      [
        spec.energy as unknown as number[],
        spec.counts as unknown as number[],
      ] as uPlot.AlignedData,
      host,
    );
    plotRef.current = u;

    // drag-to-set-window on the over element — matches MATLAB onSpecDown/Up
    const canvas = host.querySelector("canvas");
    if (!canvas) return;

    const onDown = (e: MouseEvent) => {
      dragRef.current = u.posToVal(e.offsetX - u.bbox.left, "x");
    };
    const onUp = (e: MouseEvent) => {
      if (dragRef.current == null) return;
      const x1 = u.posToVal(e.offsetX - u.bbox.left, "x");
      const lo = Math.min(dragRef.current, x1);
      const hi = Math.max(dragRef.current, x1);
      if (hi - lo > 1e-6) onDragWindow(lo, hi);
      dragRef.current = null;
    };
    canvas.addEventListener("mousedown", onDown);
    canvas.addEventListener("mouseup", onUp);

    const ro = new ResizeObserver(() => {
      if (u && host.clientWidth > 0)
        u.setSize({ width: host.clientWidth, height: 160 });
    });
    ro.observe(host);
    return () => {
      ro.disconnect();
      canvas.removeEventListener("mousedown", onDown);
      canvas.removeEventListener("mouseup", onUp);
      u.destroy();
      plotRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec, label, eLo, eHi]);

  return <div ref={hostRef} className="fvd-ws-plot" />;
}
