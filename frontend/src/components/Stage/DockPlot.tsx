// Bottom dock plot (handoff §5 <DockPlot>): uPlot line profile —
// canvas-based, handles 10⁴–10⁶ points at 60 fps.

import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

import { useStageInfo } from "../../store/stage";

export default function DockPlot() {
  const profile = useStageInfo((s) => s.profile);
  const setProfile = useStageInfo((s) => s.setProfile);
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => {
    if (!profile || !hostRef.current) return;
    const host = hostRef.current;

    const make = () => {
      plotRef.current?.destroy();
      const styles = getComputedStyle(document.documentElement);
      plotRef.current = new uPlot(
        {
          width: host.clientWidth,
          height: host.clientHeight,
          series: [
            { label: `d (${profile.unit})` },
            {
              label: "I",
              stroke: styles.getPropertyValue("--accent").trim() || "#a78bfa",
              width: 1.5,
              points: { show: false },
            },
          ],
          axes: [
            { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
            { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          ],
          legend: { show: false },
          cursor: { y: false },
        },
        [
          profile.dist,
          profile.intensity.map((v) => (v === null ? NaN : v)),
        ],
        host,
      );
    };

    make();
    const ro = new ResizeObserver(() => {
      if (plotRef.current && host.clientWidth > 0) {
        plotRef.current.setSize({
          width: host.clientWidth,
          height: host.clientHeight,
        });
      }
    });
    ro.observe(host);
    return () => {
      ro.disconnect();
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [profile]);

  if (!profile) return null;

  return (
    <div className="fvd-glass fvd-dock-plot">
      <div className="fvd-dock-head">
        <span>
          Profile — {Number(profile.length.toPrecision(4))} {profile.unit}
        </span>
        <button
          className="fvd-icon-btn"
          title="Close plot"
          onClick={() => setProfile(null)}
        >
          ✕
        </button>
      </div>
      <div ref={hostRef} className="fvd-dock-body" />
    </div>
  );
}
