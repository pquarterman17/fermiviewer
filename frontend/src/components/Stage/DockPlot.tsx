// Bottom dock plot (handoff §5 <DockPlot>): uPlot line profile —
// canvas-based, handles 10⁴–10⁶ points at 60 fps.

import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

import { sigmaBand } from "../../lib/charts/sigmaBand";
import {
  csvBaseName,
  downloadCsv,
  profileToCsv,
} from "../../lib/profileCsv";
import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";
import PlotContextSurface from "../plots/PlotContextSurface";

export default function DockPlot() {
  const profile = useStageInfo((s) => s.profile);
  const setProfile = useStageInfo((s) => s.setProfile);
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  const exportProfile = () => {
    const s = useViewer.getState();
    const id = s.activeId;
    const meta = id ? s.images[id] : undefined;
    const m = id
      ? (s.measures[id] ?? []).find((x) => x.id === profile?.measureId)
      : undefined;
    const imgW = meta?.shape[1] ?? 1;
    const imgH = meta?.shape[0] ?? 1;
    if (!profile) return;
    const csv = profileToCsv(profile, {
      imageName: meta?.name ?? "image",
      pixelSize: meta?.pixel_size ?? null,
      pixelUnit: meta?.pixel_unit ?? "px",
      kind: m?.kind ?? "profile",
      width: m?.width,
      endpointsPx: m?.pts.map((p) => ({ x: p.x * imgW, y: p.y * imgH })),
    });
    downloadCsv(`${csvBaseName(meta?.name)}_profile.csv`, csv);
  };

  useEffect(() => {
    if (!profile || !hostRef.current) return;
    const host = hostRef.current;

    const make = () => {
      plotRef.current?.destroy();
      const styles = getComputedStyle(document.documentElement);
      const accent = styles.getPropertyValue("--accent").trim() || "#a78bfa";
      const series: uPlot.Series[] = [
        { label: `d (${profile.unit})` },
        {
          label: profile.reduce === "sum" ? "I (sum)" : "I",
          stroke: accent,
          width: 1.5,
          points: { show: false },
        },
      ];
      const data: (number[] | (number | null)[])[] = [
        profile.dist,
        profile.intensity.map((v) => (v === null ? NaN : v)),
      ];
      const bands: uPlot.Band[] = [];
      // ±σ confidence band (item 3): shaded in the line's own colour,
      // appended AFTER it so its series index (1) never shifts. Absent
      // for old/cached results and for profiles with no honest σ (a
      // single-pixel line, or a reduce='sum' integral) — the backend
      // simply omits intensity_sigma in those cases.
      if (profile.intensity_sigma) {
        const cfg = sigmaBand(
          profile.intensity, profile.intensity_sigma, accent, 2, 3,
        );
        series.push(...cfg.series);
        data.push(...cfg.data);
        bands.push(cfg.band);
      }
      plotRef.current = new uPlot(
        {
          width: host.clientWidth,
          height: host.clientHeight,
          series,
          bands,
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
        data as uPlot.AlignedData,
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
          onClick={exportProfile}
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
      <PlotContextSurface
        ref={hostRef}
        plotRef={plotRef}
        label="Line profile"
        filename="line-profile.png"
        shellClassName="fvd-dock-body"
        style={{ width: "100%", height: "100%" }}
        onExportData={exportProfile}
        exportLabel="Export profile CSV"
      />
    </div>
  );
}
