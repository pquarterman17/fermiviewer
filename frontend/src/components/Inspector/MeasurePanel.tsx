// Measure + Overlay-style cards (handoff §4): measurement list mirroring
// the stage labels, ROI stats, and the persisted overlay font/colour.

import { measureProfile } from "../../lib/api";
import { physAngle, physDist } from "../../lib/geometry";
import { useStageInfo } from "../../store/stage";
import { useViewer, type Measure, type OverlayStyle } from "../../store/viewer";
import { useResults } from "../overlays/ResultsWindow";

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

// stable empty result — fresh [] per snapshot loops React (#185)
const NO_MEASURES: Measure[] = [];

type MetaLike = {
  pixel_size: number | null;
  pixel_unit: string;
} | null;

/** Distance values (calibrated when possible) from line-like measures. */
function distanceValues(
  measures: Measure[],
  img: { w: number; h: number },
  meta: MetaLike,
): number[] {
  const out: number[] = [];
  for (const m of measures) {
    if (m.kind !== "distance" && m.kind !== "profile" && m.kind !== "polyline")
      continue;
    const px = m.pts.map((p) => ({ x: p.x * img.w, y: p.y * img.h }));
    let total = 0;
    for (let i = 1; i < px.length; i++) {
      total += physDist(px[i - 1], px[i], meta?.pixel_size ?? null).value;
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
): void {
  const unit = meta?.pixel_size != null ? (meta?.pixel_unit ?? "px") : "px";
  const rows = measures.map((m, i) => {
    const px = m.pts.map((p) => ({ x: p.x * img.w, y: p.y * img.h }));
    let value = "";
    if (m.kind === "angle" && px.length === 3) {
      value = `${physAngle(px[1], px[0], px[2]).toFixed(2)}°`;
    } else if (
      m.kind === "distance" ||
      m.kind === "profile" ||
      m.kind === "polyline"
    ) {
      let d = 0;
      for (let k = 1; k < px.length; k++) {
        d += physDist(px[k - 1], px[k], meta?.pixel_size ?? null).value;
      }
      value = `${Number(d.toPrecision(6))} ${unit}`;
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
      ...px.slice(0, 2).flatMap((p) => [
        Number(p.x.toFixed(2)),
        Number(p.y.toFixed(2)),
      ]),
    ] as (string | number | null)[];
  });
  useResults.getState().show({
    title: "Measurement log",
    columns: ["#", "kind", "value", "x0", "y0", "x1", "y1"],
    rows,
  });
}

function showStats(
  measures: Measure[],
  img: { w: number; h: number },
  meta: MetaLike,
): void {
  const vals = distanceValues(measures, img, meta).sort((a, b) => a - b);
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

  if (!activeId || !meta) return null;
  const img = { w: meta.shape[1] ?? 1, h: meta.shape[0] ?? 1 };

  const valueOf = (m: Measure): string => {
    const px = m.pts.map((p) => ({ x: p.x * img.w, y: p.y * img.h }));
    if (m.kind === "angle" && px.length === 3) {
      return `${physAngle(px[1], px[0], px[2]).toFixed(1)}°`;
    }
    if ((m.kind === "distance" || m.kind === "profile") && px.length === 2) {
      const d = physDist(px[0], px[1], meta.pixel_size);
      return `${Number(d.value.toPrecision(4))} ${
        d.unit === "cal" ? meta.pixel_unit : "px"
      }`;
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
      measureProfile(activeId, px[0], px[1])
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
  const capBtn = (
    label: string,
    glyph: string,
    mode: Measure["kind"],
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
      <div className="fvd-card">
        <h3>Measure</h3>
        <div className="fvd-cap-grid">
          {capBtn("Profile", "∿", "profile")}
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
      </div>
      {measures.length > 0 && (
        <div className="fvd-card">
          <h3>Measurements</h3>
          <div className="fvd-ws-row">
            <button
              className="fvd-btn"
              title="Open the measurement log table (CSV-exportable)"
              onClick={() => showLog(measures, img, meta, roiStats)}
            >
              Log / CSV
            </button>
            <button
              className="fvd-btn"
              title="Sorted distances + summary statistics"
              onClick={() => showStats(measures, img, meta)}
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
        </div>
      )}

      <div className="fvd-card">
        <h3>Overlay style</h3>
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
      </div>
    </>
  );
}
