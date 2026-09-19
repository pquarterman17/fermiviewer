// Bottom dock plot (handoff §5 <DockPlot>): uPlot line profile —
// canvas-based, handles 10⁴–10⁶ points at 60 fps.

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

import { sigmaBand } from "../../lib/charts/sigmaBand";
import {
  csvBaseName,
  downloadCsv,
  profileToCsv,
} from "../../lib/profileCsv";
import { analyzeInterfaceWidth, type InterfaceWidthResult } from "../../lib/api/diagnostics";
import { profileGeometry } from "../../lib/profileGeometry";
import { profileSpan, withSigma, type ProfileSpan } from "../../lib/profileSpan";
import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";
import PlotContextSurface from "../plots/PlotContextSurface";

export default function DockPlot() {
  const profile = useStageInfo((s) => s.profile);
  const setProfile = useStageInfo((s) => s.setProfile);
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  // Measure mode repurposes uPlot's own drag-select: same gesture, but the
  // selection is kept instead of zooming to it. One drag answers both
  // questions a profile raises — how far apart are these two features, and
  // how sharp is the edge between them — so they are not separate tools.
  const [measuring, setMeasuring] = useState(false);
  const [span, setSpan] = useState<ProfileSpan | null>(null);
  const [fit, setFit] = useState<InterfaceWidthResult | null>(null);
  const [fitError, setFitError] = useState<string | null>(null);

  // Clear the measurement when the profile changes. A span and an edge fit
  // belong to the curve they were taken from; leaving them up under a new
  // profile shows one measurement labelled as another's.
  useEffect(() => {
    setSpan(null);
    setFit(null);
    setFitError(null);
  }, [profile?.measureId, profile?.dist, profile?.intensity]);

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
      pixelSpacing: meta?.pixel_spacing ?? null,
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
          cursor: measuring
            // setScale false: keep the selection rather than zooming into it
            ? { y: false, drag: { x: true, y: false, setScale: false } }
            : { y: false },
          hooks: measuring
            ? {
                setSelect: [
                  (u) => {
                    if (u.select.width <= 0) return;
                    const a = u.posToVal(u.select.left, "x");
                    const b = u.posToVal(u.select.left + u.select.width, "x");
                    setFit(null);
                    setFitError(null);
                    setSpan(profileSpan(profile.dist, profile.intensity, a, b));
                  },
                ],
              }
            : {},
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
  }, [profile, measuring]);

  if (!profile) return null;

  const geom = (() => {
    const s = useViewer.getState();
    const id = s.activeId;
    const meta = id ? s.images[id] : undefined;
    const m = id
      ? (s.measures[id] ?? []).find((x) => x.id === profile.measureId)
      : undefined;
    return profileGeometry(m, {
      w: meta?.shape[1] ?? 1,
      h: meta?.shape[0] ?? 1,
    });
  })();

  const runFit = () => {
    if (!span) return;
    setFitError(null);
    analyzeInterfaceWidth(span.x, span.y)
      .then(setFit)
      .catch((e: Error) => {
        setFit(null);
        setFitError(e.message);
      });
  };

  return (
    <div className="fvd-glass fvd-dock-plot">
      <div className="fvd-dock-head">
        <span>
          Profile — {Number(profile.length.toPrecision(4))} {profile.unit}
          {geom && (
            <span
              className="dim"
              title="Direction of integration and the perpendicular width averaged into each sample"
            >
              {" · "}{geom.angleDeg.toFixed(1)}°
              {geom.widthPx > 1 && ` · ${geom.widthPx} px wide`}
            </span>
          )}
        </span>
        <button
          className={`fvd-icon-btn${measuring ? " active" : ""}`}
          title={
            measuring
              ? "Stop measuring (drag zooms again)"
              : "Measure: drag across the plot for a distance, then fit the edge inside it"
          }
          // the glyph is the whole label otherwise, which leaves a screen
          // reader announcing "↔ button"
          aria-label="Measure span"
          aria-pressed={measuring}
          onClick={() => {
            setMeasuring((on) => !on);
            setSpan(null);
            setFit(null);
            setFitError(null);
          }}
        >
          ↔
        </button>
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
      {measuring && (
        <div className="fvd-dock-measure">
          {!span && <span className="dim">Drag across the plot to measure.</span>}
          {span && (
            <>
              <span>
                Δ {Number(span.length.toPrecision(4))} {profile.unit}
              </span>
              <span className="dim">
                step {Number(span.step.toPrecision(3))}
              </span>
              <button className="fvd-btn" onClick={runFit} title="Fit an erf edge to the selected samples">
                Fit edge
              </button>
            </>
          )}
          {fit && (
            <>
              <span>
                centre {withSigma(fit.center, fit.center_sigma, profile.unit)}
              </span>
              <span>
                10-90% {withSigma(fit.width_10_90, fit.width_sigma, profile.unit)}
              </span>
              {/* r² sits beside the widths on purpose: a tight-looking σ on a
                  fit that did not describe the data is the misreading this
                  readout has to prevent */}
              <span className="dim">r² {fit.r_squared.toFixed(3)}</span>
            </>
          )}
          {fitError && <span className="fvd-quality poor">{fitError}</span>}
        </div>
      )}
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
