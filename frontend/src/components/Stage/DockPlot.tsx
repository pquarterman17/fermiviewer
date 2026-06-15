// Bottom dock plot (handoff §5 <DockPlot>): uPlot line profile —
// canvas-based, handles 10⁴–10⁶ points at 60 fps.

import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

import {
  csvBaseName,
  downloadCsv,
  profileToCsv,
} from "../../lib/profileCsv";
import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";

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
              label: profile.reduce === "sum" ? "I (sum)" : "I",
              stroke: styles.getPropertyValue("--accent").trim() || "#a78bfa",
              width: 1.5,
              points: { show: false },
            },
          ],
          // x is calibrated distance, not time — uPlot defaults to a time
          // axis, which renders 0–N nm as clock times (the bug this fixes)
          scales: { x: { time: false } },
          axes: [
            {
              stroke: "#888",
              grid: { stroke: "rgba(128,128,128,0.15)" },
              values: (_u, vals) => vals.map((v) => `${v} ${profile.unit}`),
            },
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
          title="Download profile as CSV (provenance header + calibrated x-axis)"
          onClick={() => {
            const s = useViewer.getState();
            const id = s.activeId;
            const meta = id ? s.images[id] : undefined;
            const m = id
              ? (s.measures[id] ?? []).find((x) => x.id === profile.measureId)
              : undefined;
            const imgW = meta?.shape[1] ?? 1;
            const imgH = meta?.shape[0] ?? 1;
            const csv = profileToCsv(profile, {
              imageName: meta?.name ?? "image",
              pixelSize: meta?.pixel_size ?? null,
              pixelUnit: meta?.pixel_unit ?? "px",
              kind: m?.kind ?? "profile",
              width: m?.width,
              endpointsPx: m?.pts.map((p) => ({ x: p.x * imgW, y: p.y * imgH })),
            });
            downloadCsv(`${csvBaseName(meta?.name)}_profile.csv`, csv);
          }}
        >
          ⤓
        </button>
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
