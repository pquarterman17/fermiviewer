// Measure + Overlay-style cards (handoff §4): measurement list mirroring
// the stage labels, ROI stats, and the persisted overlay font/colour.

import { Fragment, useMemo, useState } from "react";

import {
  measureBoxProfile,
  measureProfile,
  type ProfileReduce,
} from "../../lib/api";
import { computeMeasureStats } from "../../lib/measureStats";
import { fuzzy } from "../../lib/fuzzy";
import {
  areaPxToPhysical,
  physAngle,
  polygonStats,
  tiltDist,
} from "../../lib/geometry";
import { MEASURE_GROUPS, MEASURE_TOOLS } from "../../lib/measureTools";
import {
  boxProfileToCsv,
  csvBaseName,
  downloadCsv,
} from "../../lib/profileCsv";
import { useStageInfo } from "../../store/stage";
import { useViewer, type Measure } from "../../store/viewer";
import Card from "./Card";
import {
  END_SYMBOLS,
  KIND_GLYPH,
  LINE_WIDTHS,
  NO_MEASURES,
  showLog,
  showRoiHistogram,
  showStats,
  SIZES,
  SWATCHES,
} from "./measurePanelUtils";
import TiltCorrectionCard from "./TiltCorrectionCard";
import { useCollapsedGroups } from "./useCollapsedGroups";

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

  /** Aggregate statistics across all measures — pure, recomputed when
   *  measures / roiStats / tilt change.  Stable empty reference when there
   *  are no measures (no ?! inside the selector body per Zustand rule). */
  const aggStats = useMemo(
    () =>
      meta && measures.length > 0
        ? computeMeasureStats({
            measures,
            img: { w: meta.shape[1] ?? 1, h: meta.shape[0] ?? 1 },
            pixelSize: meta.pixel_size ?? null,
            pixelUnit: meta.pixel_unit ?? "px",
            tilt,
            roiStats,
          })
        : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [measures, roiStats, tilt, meta?.shape, meta?.pixel_size, meta?.pixel_unit],
  );

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
    if (m.kind === "polygon" || m.kind === "lasso") {
      const areaPx2 = polygonStats(px).areaPx2;
      const areaPhys = areaPxToPhysical(areaPx2, meta.pixel_size ?? null);
      return areaPhys != null
        ? `${Number(areaPhys.toPrecision(4))} ${meta.pixel_unit}²`
        : `${Number(areaPx2.toPrecision(4))} px²`;
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

  /** Integrate a rectangle ROI along both axes and download one CSV. */
  const onExportBoxCsv = (m: Measure) => {
    if (!activeId || m.pts.length < 2) return;
    const reduce = useViewer.getState().profileReduce;
    const px = m.pts.map((p) => ({ x: p.x * img.w, y: p.y * img.h }));
    measureBoxProfile(activeId, px[0], px[1], reduce)
      .then((b) => {
        const csv = boxProfileToCsv(b, {
          imageName: meta.name,
          pixelUnit: meta.pixel_unit,
          kind: m.kind,
        });
        downloadCsv(`${csvBaseName(meta.name)}_box-profile.csv`, csv);
        setStatus(`box profile exported (${reduce})`);
      })
      .catch((e: Error) => setStatus(e.message));
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
  const [toolQuery, setToolQuery] = useState("");
  const { collapsed, toggle } = useCollapsedGroups("measure");
  const q = toolQuery.trim();
  const visibleTools = q
    ? MEASURE_TOOLS.filter((t) => fuzzy(q, t.label) !== null)
    : MEASURE_TOOLS;

  return (
    <>
      <Card title="Measure" defaultOpen={false}>
        <div className="fvd-cmd-search">
          <span className="ico">⌕</span>
          <input
            value={toolQuery}
            placeholder="Filter measure tools…"
            onChange={(e) => setToolQuery(e.target.value)}
          />
        </div>
        <div className="fvd-cmd-list">
          {MEASURE_GROUPS.map((group) => {
            const tools = visibleTools.filter((t) => t.group === group);
            if (tools.length === 0) return null;
            // a search query forces every group open so matches aren't hidden
            const open = q !== "" || !collapsed.has(group);
            return (
              <Fragment key={group}>
                <button
                  className="fvd-cmd-group"
                  onClick={() => toggle(group)}
                  title={open ? "Collapse group" : "Expand group"}
                >
                  <span className="lbl">
                    <span className="chev">{open ? "▾" : "▸"}</span>
                    {group}
                  </span>
                  <span className="count">{tools.length}</span>
                </button>
                {open &&
                  tools.map((t) => (
                    <button
                      key={t.kind}
                      className={`fvd-cmd-row${captureMode === t.kind ? " active" : ""}`}
                      onClick={() =>
                        setCaptureMode(captureMode === t.kind ? "none" : t.kind)
                      }
                      title={`Arm the ${t.label} tool — drag on the image to place it (click again to disarm)`}
                    >
                      <span className="glyph">{t.glyph}</span>
                      <span className="label">{t.label}</span>
                      {captureMode === t.kind && <span className="dot" />}
                    </button>
                  ))}
              </Fragment>
            );
          })}
          {visibleTools.length === 0 && (
            <div className="fvd-cmd-empty">No tools match “{q}”.</div>
          )}
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
        <Card title="Measurements" count={measures.length} defaultOpen={false}>
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
          {aggStats && aggStats.groups.length > 0 && (
            <div className="fvd-mstats-summary">
              {aggStats.groups.map((g) => (
                <div key={g.label} className="fvd-mstats-group">
                  <div className="fvd-mstats-header">
                    {g.label}
                    <span className="fvd-mstats-n">N={g.count}</span>
                  </div>
                  <div className="fvd-mstats-row">
                    <span className="k">mean</span>
                    <span className="v">
                      {Number(g.mean.toPrecision(5))} {g.unit}
                    </span>
                  </div>
                  <div className="fvd-mstats-row">
                    <span className="k">± std</span>
                    <span className="v">
                      {Number(g.std.toPrecision(5))} {g.unit}
                    </span>
                  </div>
                  <div className="fvd-mstats-row">
                    <span className="k">min</span>
                    <span className="v">
                      {Number(g.min.toPrecision(5))} {g.unit}
                    </span>
                  </div>
                  <div className="fvd-mstats-row">
                    <span className="k">max</span>
                    <span className="v">
                      {Number(g.max.toPrecision(5))} {g.unit}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
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
                  useViewer.getState().setMeasureStyle(activeId, sel.id, {
                    color: e.target.value,
                  })
                }
              />
              {sel.color && (
                <button
                  className="fvd-btn"
                  onClick={() =>
                    useViewer.getState().setMeasureStyle(activeId, sel.id, {
                      color: undefined,
                    })
                  }
                  title="Clear this item's colour override (use overlay default)"
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
              {sel.kind === "roi" && (
                <button
                  className="fvd-btn"
                  title={`Integrate this box along both axes → CSV (uses the Reduce mode: ${profileReduce})`}
                  onClick={() => onExportBoxCsv(sel)}
                >
                  Box profile CSV
                </button>
              )}
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

      <Card title="Overlay style" defaultOpen={false}>
        <div className="fvd-slider-row">
          <span className="k">Size</span>
          <div className="fvd-seg">
            {SIZES.map((sz) => (
              <button
                key={sz}
                className={`fvd-seg-btn${overlay.size === sz ? " active" : ""}`}
                onClick={() => setOverlay({ size: sz })}
                title={`Set overlay label size to ${sz}`}
              >
                {sz}
              </button>
            ))}
          </div>
        </div>
        <div className="fvd-slider-row">
          <span className="k">Line width</span>
          <div className="fvd-seg">
            {LINE_WIDTHS.map((w) => (
              <button
                key={w}
                className={`fvd-seg-btn${(overlay.lineWidth ?? 2.5) === w ? " active" : ""}`}
                onClick={() => setOverlay({ lineWidth: w })}
                title={`Set overlay line width to ${w} px`}
              >
                {w}
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
                title="Use this overlay colour"
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

      <TiltCorrectionCard activeId={activeId} tilt={tilt} setTilt={setTilt} />
    </>
  );
}
