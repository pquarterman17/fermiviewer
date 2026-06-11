// Measure + Overlay-style cards (handoff §4): measurement list mirroring
// the stage labels, ROI stats, and the persisted overlay font/colour.

import { measureProfile, type ProfileReduce } from "../../lib/api";
import {
  physAngle,
  physDist,
  tiltDist,
  type TiltSettings,
} from "../../lib/geometry";
import { useStageInfo } from "../../store/stage";
import {
  useViewer,
  type CaptureMode,
  type EndSymbol,
  type Measure,
  type OverlayStyle,
} from "../../store/viewer";
import { useResults } from "../overlays/ResultsWindow";
import Card from "./Card";

const KIND_GLYPH: Record<Measure["kind"], string> = {
  distance: "↔",
  profile: "∿",
  angle: "∠",
  roi: "▭",
  ellipse: "◯",
  polyline: "⌇",
  text: "T",
  arrow: "➹",
  box: "□",
  circle: "◌",
};

const SIZES: OverlayStyle["size"][] = ["S", "M", "L", "XL"];
const SWATCHES = ["#ffffff", "#22d3ee", "#fbbf24", "#f472b6", "#a3e635"];
const END_SYMBOLS: { sym: EndSymbol; label: string }[] = [
  { sym: "bar", label: "|" },
  { sym: "none", label: "—" },
  { sym: "circle", label: "○" },
  { sym: "square", label: "□" },
  { sym: "cross", label: "×" },
];

// stable empty result — fresh [] per snapshot loops React (#185)
const NO_MEASURES: Measure[] = [];

type MetaLike = {
  pixel_size: number | null;
  pixel_unit: string;
} | null;

/** Distance values (calibrated when possible) from line-like measures.
 *  Applies the per-image tilt correction (#34) when active so stats
 *  match the on-screen labels. */
function distanceValues(
  measures: Measure[],
  img: { w: number; h: number },
  meta: MetaLike,
  tilt: TiltSettings | null,
): number[] {
  const out: number[] = [];
  for (const m of measures) {
    if (m.kind !== "distance" && m.kind !== "profile" && m.kind !== "polyline")
      continue;
    const px = m.pts.map((p) => ({ x: p.x * img.w, y: p.y * img.h }));
    let total = 0;
    for (let i = 1; i < px.length; i++) {
      total += tiltDist(px[i - 1], px[i], meta?.pixel_size ?? null, tilt).value;
    }
    out.push(total);
  }
  return out;
}

function showLog(
  measures: Measure[],
  img: { w: number; h: number },
  meta: MetaLike,
  roiStats: Record<string, { mean: number; std: number }>,
  tilt: TiltSettings | null,
): void {
  const unit = meta?.pixel_size != null ? (meta?.pixel_unit ?? "px") : "px";
  // #34: with tilt active the log/CSV carries BOTH columns — value is
  // the corrected length (matches labels), raw is the uncorrected one
  const tiltOn = tilt != null && tilt.angle !== 0;
  const rows = measures.map((m, i) => {
    const px = m.pts.map((p) => ({ x: p.x * img.w, y: p.y * img.h }));
    let value = "";
    let raw: string | null = tiltOn ? "" : null;
    if (m.kind === "angle" && px.length === 3) {
      value = `${physAngle(px[1], px[0], px[2]).toFixed(2)}°`;
    } else if (
      m.kind === "distance" ||
      m.kind === "profile" ||
      m.kind === "polyline"
    ) {
      let d = 0;
      let dRaw = 0;
      for (let k = 1; k < px.length; k++) {
        d += tiltDist(px[k - 1], px[k], meta?.pixel_size ?? null, tilt).value;
        dRaw += physDist(px[k - 1], px[k], meta?.pixel_size ?? null).value;
      }
      value = `${Number(d.toPrecision(6))} ${unit}`;
      if (tiltOn) raw = `${Number(dRaw.toPrecision(6))} ${unit}`;
    } else if (m.kind === "roi" || m.kind === "ellipse") {
      const s = roiStats[m.id];
      value = s ? `μ=${s.mean} σ=${s.std}` : "";
    } else {
      value = m.text ?? "";
    }
    return [
      i + 1,
      m.kind,
      value,
      ...(tiltOn ? [raw] : []),
      ...px.slice(0, 2).flatMap((p) => [
        Number(p.x.toFixed(2)),
        Number(p.y.toFixed(2)),
      ]),
    ] as (string | number | null)[];
  });
  useResults.getState().show({
    title: tiltOn
      ? `Measurement log (tilt ${tilt.angle}° ${tilt.axis}, ${tilt.geometry})`
      : "Measurement log",
    columns: tiltOn
      ? ["#", "kind", "corrected", "raw", "x0", "y0", "x1", "y1"]
      : ["#", "kind", "value", "x0", "y0", "x1", "y1"],
    rows,
  });
}

/** Binned intensity histogram of the selected ROI/ellipse, from the
 *  client-side raster (no request). */
function showRoiHistogram(m: Measure, img: { w: number; h: number }): void {
  const r = useStageInfo.getState().raster;
  if (!r || m.pts.length < 2) {
    useViewer.getState().setStatus("histogram: raster not loaded");
    return;
  }
  const x0 = Math.max(0, Math.floor(Math.min(m.pts[0].x, m.pts[1].x) * img.w));
  const x1 = Math.min(r.w, Math.ceil(Math.max(m.pts[0].x, m.pts[1].x) * img.w));
  const y0 = Math.max(0, Math.floor(Math.min(m.pts[0].y, m.pts[1].y) * img.h));
  const y1 = Math.min(r.h, Math.ceil(Math.max(m.pts[0].y, m.pts[1].y) * img.h));
  const BINS = 64;
  const counts = new Array<number>(BINS).fill(0);
  const cx = (x0 + x1 - 1) / 2;
  const cy = (y0 + y1 - 1) / 2;
  const rx = Math.max((x1 - x0) / 2, 0.5);
  const ry = Math.max((y1 - y0) / 2, 0.5);
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      if (
        m.kind === "ellipse" &&
        ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 > 1
      ) {
        continue;
      }
      counts[Math.min(BINS - 1, r.data[y * r.w + x] >> 10)]++;
    }
  }
  const span = r.vmax - r.vmin || 1;
  useResults.getState().show({
    title: `ROI histogram (${m.kind})`,
    columns: ["bin centre", "count"],
    rows: counts.map((c, b) => [
      Number((r.vmin + ((b + 0.5) / BINS) * span).toPrecision(6)),
      c,
    ]),
  });
}

function showStats(
  measures: Measure[],
  img: { w: number; h: number },
  meta: MetaLike,
  tilt: TiltSettings | null,
): void {
  const vals = distanceValues(measures, img, meta, tilt).sort((a, b) => a - b);
  if (vals.length === 0) {
    useViewer.getState().setStatus("stats: no distance-like measurements");
    return;
  }
  const unit = meta?.pixel_size != null ? (meta?.pixel_unit ?? "px") : "px";
  const mean = vals.reduce((s, v) => s + v, 0) / vals.length;
  const std = Math.sqrt(
    vals.reduce((s, v) => s + (v - mean) ** 2, 0) / vals.length,
  );
  const rows: (string | number | null)[][] = vals.map((v, i) => [
    i + 1,
    Number(v.toPrecision(6)),
  ]);
  rows.push(["mean", Number(mean.toPrecision(6))]);
  rows.push(["std", Number(std.toPrecision(6))]);
  rows.push(["min", Number(vals[0].toPrecision(6))]);
  rows.push(["max", Number(vals[vals.length - 1].toPrecision(6))]);
  useResults.getState().show({
    title: `Distance statistics (${unit})`,
    columns: ["#", `value (${unit})`],
    rows,
  });
}

export default function MeasurePanel() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const measures = useViewer((s) =>
    s.activeId ? (s.measures[s.activeId] ?? NO_MEASURES) : NO_MEASURES,
  );
  const selected = useViewer((s) => s.selectedMeasure);
  const setSelected = useViewer((s) => s.setSelectedMeasure);
  const removeMeasure = useViewer((s) => s.removeMeasure);
  const roiStats = useViewer((s) => s.roiStats);
  const overlay = useViewer((s) => s.overlay);
  const setOverlay = useViewer((s) => s.setOverlay);
  const setProfile = useStageInfo((s) => s.setProfile);
  const setStatus = useViewer((s) => s.setStatus);
  const tilt = useViewer((s) =>
    s.activeId ? (s.tilts[s.activeId] ?? null) : null,
  );
  const setTilt = useViewer((s) => s.setTilt);

  if (!activeId || !meta) return null;
  const img = { w: meta.shape[1] ?? 1, h: meta.shape[0] ?? 1 };

  const valueOf = (m: Measure): string => {
    const px = m.pts.map((p) => ({ x: p.x * img.w, y: p.y * img.h }));
    if (m.kind === "angle" && px.length === 3) {
      return `${physAngle(px[1], px[0], px[2]).toFixed(1)}°`;
    }
    if ((m.kind === "distance" || m.kind === "profile") && px.length === 2) {
      const d = tiltDist(px[0], px[1], meta.pixel_size, tilt);
      const theta = tilt != null && tilt.angle !== 0 ? " θ" : "";
      return `${Number(d.value.toPrecision(4))} ${
        d.unit === "cal" ? meta.pixel_unit : "px"
      }${theta}`;
    }
    if (m.kind === "roi" || m.kind === "ellipse") {
      const s = roiStats[m.id];
      return s ? `μ ${Number(s.mean.toPrecision(4))}` : "…";
    }
    if (
      m.kind === "text" ||
      m.kind === "arrow" ||
      m.kind === "box" ||
      m.kind === "circle"
    ) {
      return m.text ?? "";
    }
    return "";
  };

  const onSelect = (m: Measure) => {
    setSelected(m.id);
    if (m.kind === "profile") {
      const px = m.pts.map((p) => ({ x: p.x * img.w, y: p.y * img.h }));
      measureProfile(activeId, px[0], px[1], m.width ?? 1, tilt, profileReduce)
        .then((r) => setProfile({ ...r, measureId: m.id }))
        .catch((e: Error) => setStatus(e.message));
    }
  };

  const sel = measures.find((m) => m.id === selected);
  const selStats =
    sel?.kind === "roi" || sel?.kind === "ellipse"
      ? roiStats[sel.id]
      : undefined;
  const selIsAnnotation =
    sel !== undefined &&
    (sel.kind === "text" ||
      sel.kind === "arrow" ||
      sel.kind === "box" ||
      sel.kind === "circle");
  const setMeasureText = useViewer((s) => s.setMeasureText);

  const captureMode = useViewer((s) => s.captureMode);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const profileWidth = useViewer((s) => s.profileWidth);
  const setProfileWidth = useViewer((s) => s.setProfileWidth);
  const profileReduce = useViewer((s) => s.profileReduce);
  const setProfileReduce = useViewer((s) => s.setProfileReduce);
  const capBtn = (
    label: string,
    glyph: string,
    mode: CaptureMode,
  ) => (
    <button
      className={`fvd-cap-btn${captureMode === mode ? " active" : ""}`}
      onClick={() => setCaptureMode(captureMode === mode ? "none" : mode)}
    >
      <span className="glyph">{glyph}</span> {label}
    </button>
  );

  return (
    <>
      <Card title="Measure">
        <div className="fvd-cap-grid">
          {capBtn("Profile", "∿", "profile")}
          {capBtn("Box Prof", "⧈", "box-profile")}
          {capBtn("Distance", "↔", "distance")}
          {capBtn("Angle", "∠", "angle")}
          {capBtn("Polyline", "⌇", "polyline")}
          {capBtn("ROI", "▭", "roi")}
          {capBtn("Ellipse", "◯", "ellipse")}
        </div>
        <div className="fvd-cap-grid">
          {capBtn("Text", "T", "text")}
          {capBtn("Arrow", "➹", "arrow")}
          {capBtn("Box", "□", "box")}
          {capBtn("Circle", "◌", "circle")}
        </div>
        <div className="fvd-profile-opts">
          <span className="fvd-profile-opts-label">Profile options</span>
          <div className="fvd-slider-row">
            <span className="k">Width (px)</span>
            <input
              type="number"
              min={1}
              max={99}
              value={profileWidth}
              style={{ width: 52 }}
              title="Perpendicular averaging width for profile captures"
              onChange={(e) => setProfileWidth(Number(e.target.value) || 1)}
            />
          </div>
          <div className="fvd-slider-row">
            <span className="k">Reduce</span>
            <div className="fvd-seg">
              {(["mean", "sum"] as ProfileReduce[]).map((r) => (
                <button
                  key={r}
                  className={`fvd-seg-btn${profileReduce === r ? " active" : ""}`}
                  title={
                    r === "mean"
                      ? "Average intensity across box width (default)"
                      : "Sum counts across box width — for quantitative integration"
                  }
                  onClick={() => setProfileReduce(r)}
                >
                  {r === "mean" ? "Mean" : "Sum"}
                </button>
              ))}
            </div>
          </div>
        </div>
      </Card>
      {measures.length > 0 && (
        <Card title="Measurements">
          <div className="fvd-ws-row">
            <button
              className="fvd-btn"
              title="Open the measurement log table (CSV-exportable)"
              onClick={() => showLog(measures, img, meta, roiStats, tilt)}
            >
              Log / CSV
            </button>
            <button
              className="fvd-btn"
              title="Sorted distances + summary statistics"
              onClick={() => showStats(measures, img, meta, tilt)}
            >
              Stats
            </button>
          </div>
          {measures.map((m, i) => (
            <div
              key={m.id}
              className={`fvd-measure-row${m.id === selected ? " selected" : ""}`}
              onClick={() => onSelect(m)}
            >
              <span className="glyph">{KIND_GLYPH[m.kind]}</span>
              <span className="name">
                {m.kind} {i + 1}
              </span>
              <span className="val">{valueOf(m)}</span>
              <button
                className="fvd-icon-btn"
                title="Delete  Del"
                onClick={(e) => {
                  e.stopPropagation();
                  removeMeasure(activeId, m.id);
                }}
              >
                ✕
              </button>
            </div>
          ))}
          {sel && (
            <div className="fvd-slider-row">
              <span className="k">Item color</span>
              <input
                type="color"
                value={sel.color ?? overlay.color}
                style={{ width: 28, height: 20, padding: 0, border: "none" }}
                onChange={(e) =>
                  useViewer
                    .getState()
                    .setMeasureStyle(activeId, sel.id, {
                      color: e.target.value,
                    })
                }
              />
              {sel.color && (
                <button
                  className="fvd-btn"
                  onClick={() =>
                    useViewer
                      .getState()
                      .setMeasureStyle(activeId, sel.id, {
                        color: undefined,
                      })
                  }
                >
                  Reset
                </button>
              )}
            </div>
          )}
          {selIsAnnotation && sel && (
            <div className="fvd-slider-row">
              <span className="k">Text</span>
              <input
                style={{ flex: 1 }}
                value={sel.text ?? ""}
                placeholder="caption…"
                onChange={(e) =>
                  setMeasureText(activeId, sel.id, e.target.value)
                }
              />
            </div>
          )}
          {selStats && sel && (
            <div className="fvd-ws-row">
              <button
                className="fvd-btn"
                title="Binned intensity histogram of this ROI (CSV-able)"
                onClick={() => showRoiHistogram(sel, img)}
              >
                ROI histogram
              </button>
            </div>
          )}
          {selStats && (
            <div className="fvd-roi-stats">
              {(
                [
                  ["mean", selStats.mean],
                  ["std", selStats.std],
                  ["min", selStats.min],
                  ["max", selStats.max],
                  ["area", selStats.area],
                ] as const
              ).map(([k, v]) => (
                <div key={k} className="fvd-meta-row">
                  <span className="k">
                    {k === "area" ? `area (${selStats.unit}²)` : k}
                  </span>
                  <span className="v">{Number(v.toPrecision(5))}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      <Card title="Overlay style">
        <div className="fvd-slider-row">
          <span className="k">Size</span>
          <div className="fvd-seg">
            {SIZES.map((sz) => (
              <button
                key={sz}
                className={`fvd-seg-btn${overlay.size === sz ? " active" : ""}`}
                onClick={() => setOverlay({ size: sz })}
              >
                {sz}
              </button>
            ))}
          </div>
        </div>
        <div className="fvd-slider-row">
          <span className="k">Color</span>
          <div className="fvd-swatches">
            {SWATCHES.map((c) => (
              <button
                key={c}
                className={`fvd-swatch${overlay.color === c ? " active" : ""}`}
                style={{ background: c }}
                onClick={() => setOverlay({ color: c })}
              />
            ))}
          </div>
        </div>
        <div className="fvd-slider-row">
          <span className="k">End symbol</span>
          <div className="fvd-seg">
            {END_SYMBOLS.map(({ sym, label }) => (
              <button
                key={sym}
                className={`fvd-seg-btn${(overlay.endSymbol ?? "bar") === sym ? " active" : ""}`}
                title={sym}
                onClick={() => setOverlay({ endSymbol: sym })}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </Card>

      <Card title="Tilt correction">
        <div className="fvd-ws-note">
          Corrects distance/profile/polyline lengths for stage tilt
          (#34). 0° = off; labels gain a θ marker when active.
        </div>
        <div className="fvd-slider-row">
          <span className="k">Angle (°)</span>
          <input
            type="number"
            min={-89.9}
            max={89.9}
            step={0.1}
            style={{ width: 64 }}
            value={tilt?.angle ?? 0}
            onChange={(e) => {
              const v = Math.max(-89.9, Math.min(89.9, Number(e.target.value) || 0));
              setTilt(activeId, {
                angle: v,
                axis: tilt?.axis ?? "Y",
                geometry: tilt?.geometry ?? "cross-section",
                seedAngle: tilt?.seedAngle,
              });
            }}
          />
          {tilt?.seedAngle != null &&
            (tilt?.angle ?? 0) !== Number(tilt.seedAngle.toFixed(2)) && (
              <button
                className="fvd-btn"
                title="Apply the stage tilt found in the file metadata"
                onClick={() =>
                  setTilt(activeId, {
                    angle: Number(tilt.seedAngle!.toFixed(2)),
                    axis: tilt.axis,
                    geometry: tilt.geometry,
                    seedAngle: tilt.seedAngle,
                  })
                }
              >
                Stage: {tilt.seedAngle.toFixed(1)}°
              </button>
            )}
        </div>
        <div className="fvd-slider-row">
          <span className="k">Axis</span>
          <div className="fvd-seg">
            {(["X", "Y"] as const).map((ax) => (
              <button
                key={ax}
                className={`fvd-seg-btn${(tilt?.axis ?? "Y") === ax ? " active" : ""}`}
                onClick={() =>
                  setTilt(activeId, {
                    angle: tilt?.angle ?? 0,
                    axis: ax,
                    geometry: tilt?.geometry ?? "cross-section",
                    seedAngle: tilt?.seedAngle,
                  })
                }
              >
                {ax}
              </button>
            ))}
          </div>
        </div>
        <div className="fvd-slider-row">
          <span className="k">Geometry</span>
          <div className="fvd-seg">
            {(
              [
                // MATLAB names on the buttons; formula on hover
                ["cross-section", "Cross-section",
                 "1/sin θ — FIB cross-section"],
                ["surface", "Plan-view",
                 "1/cos θ — tilted plan-view surface"],
              ] as const
            ).map(([g, lbl, hint]) => (
              <button
                key={g}
                className={`fvd-seg-btn${(tilt?.geometry ?? "cross-section") === g ? " active" : ""}`}
                title={hint}
                onClick={() =>
                  setTilt(activeId, {
                    angle: tilt?.angle ?? 0,
                    axis: tilt?.axis ?? "Y",
                    geometry: g,
                    seedAngle: tilt?.seedAngle,
                  })
                }
              >
                {lbl}
              </button>
            ))}
          </div>
        </div>
      </Card>
    </>
  );
}
