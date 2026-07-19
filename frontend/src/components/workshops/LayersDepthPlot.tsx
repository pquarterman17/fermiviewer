import { useEffect, useRef } from "react";
import uPlot from "uplot";

import type { LayersResult } from "../../lib/api";

export default function LayersDepthPlot({ r }: { r: LayersResult }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    plotRef.current?.destroy();
    const accent =
      getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() ||
      "#a78bfa";
    const interfaces = r.interfaces.map((i) => i.position);
    plotRef.current = new uPlot(
      {
        width: host.clientWidth || 300,
        height: 160,
        scales: { x: { time: false } },
        series: [
          { label: "depth (px)" },
          { label: "I", stroke: accent, width: 1.5, points: { show: false } },
        ],
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
        ],
        legend: { show: false },
        cursor: { y: false },
        hooks: {
          draw: [
            (u) => {
              const ctx = u.ctx;
              ctx.save();
              ctx.strokeStyle = "#f59e0b";
              ctx.setLineDash([4, 3]);
              ctx.lineWidth = 1;
              for (const p of interfaces) {
                const x = u.valToPos(p, "x", true);
                ctx.beginPath();
                ctx.moveTo(x, u.bbox.top);
                ctx.lineTo(x, u.bbox.top + u.bbox.height);
                ctx.stroke();
              }
              ctx.restore();
            },
          ],
        },
      },
      [r.depth_pos, r.depth_profile] as uPlot.AlignedData,
      host,
    );
    const ro = new ResizeObserver(() => {
      if (plotRef.current && host.clientWidth > 0) {
        plotRef.current.setSize({ width: host.clientWidth, height: 160 });
      }
    });
    ro.observe(host);
    return () => {
      ro.disconnect();
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [r]);

  return <div ref={hostRef} className="fvd-ws-plot" />;
}
