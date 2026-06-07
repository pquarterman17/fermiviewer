// Measure + Overlay-style cards (handoff §4): measurement list mirroring
// the stage labels, ROI stats, and the persisted overlay font/colour.

import { measureProfile } from "../../lib/api";
import { physAngle, physDist } from "../../lib/geometry";
import { useStageInfo } from "../../store/stage";
import { useViewer, type Measure, type OverlayStyle } from "../../store/viewer";

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
};

const SIZES: OverlayStyle["size"][] = ["S", "M", "L", "XL"];
const SWATCHES = ["#ffffff", "#22d3ee", "#fbbf24", "#f472b6", "#a3e635"];

// stable empty result — fresh [] per snapshot loops React (#185)
const NO_MEASURES: Measure[] = [];

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
    if (m.kind === "text" || m.kind === "arrow" || m.kind === "box") {
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
  const selStats = sel?.kind === "roi" ? roiStats[sel.id] : undefined;

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
