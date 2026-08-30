// Regions card (Inspector, plan item 15 — the area-measurement
// deliverable): a per-image table of polygon/lasso regions with area in
// physical units, and a Copy/Export CSV action that actually gets a
// measured area out of the app. Rows are recomputed from the active
// image's measures + calibration on every render (ADR 0002) — nothing
// here is stored, so recalibrating pixel_size updates every row with no
// migration step.
//
// Item 14 (polygon + lasso measure kinds) has not landed on this branch
// yet, so no capture tool can draw one — this card is wired ahead of
// that PR merging. `regionRows` (lib/regionTable.ts) selects region
// measures by a REGION_KINDS set, not by narrowing MeasureKind, so this
// card lights up with zero changes here once 14 merges.
//
// Plan item 16 (edge auto-detect assist): "Detect Region" below calls
// POST /api/regions/propose (routes/regions.py) with a seed point and
// lands the returned outline via the store's ordinary addMeasure action,
// kind "polygon" — there is no separate "detected region" concept, so it
// shows up in the table above with zero special-casing, immediately
// draggable/correctable like any hand-drawn polygon (addMeasure already
// selects the new measure, which is what makes its vertices live).
//
// SHAPE_ANALYSIS_PLAN.md Wave-2 #5 (GUI wiring): each region row also gets
// a "Fit" action that sends that polygon's vertices to
// POST /api/analyze/fit-shape (routes/shape_id.py) and shows both the
// circle and ellipse fit compactly under the row — both always shown
// together with their RMS residual; nothing here auto-picks a "better"
// fit, the user judges (same advisory philosophy as the shape-class
// badge in ParticlesMode). No new overlay machinery: drawing the fitted
// shape would need Stage/MeasureOverlay.tsx (outside this card's file
// ownership) to grow a new rotated-ellipse render path, so this is a
// numeric readout only, exactly the fallback the plan spec allows.

import { useMemo, useState } from "react";

import { fitShape, proposeRegion, type FitShapeResponse } from "../../lib/api/regions";
import { displayArea } from "../../lib/lengthUnits";
import {
  regionCsvColumns,
  regionCsvRows,
  regionRows,
} from "../../lib/regionTable";
import { downloadCsv, exportBaseName, tableToCsv } from "../../lib/resultsExport";
import { useViewer, type Measure } from "../../store/viewer";
import Card from "./Card";

// stable fallback — never return a fresh [] inside a selector
const NO_MEASURES: Measure[] = [];

// The endpoint fits both shapes together (route calls fit_circle then
// fit_ellipse — routes/shape_id.py) rather than picking one: circle needs
// >= 3 points, ellipse >= 5. A 3-4 vertex input would fit the circle fine
// but 422 on the ellipse; rather than surface a partial success / partial
// 422, the action is disabled below 5 vertices outright — a 3-vertex
// "ellipse" is meaningless anyway (a triangle fits infinitely many), so
// there is no useful result being withheld.
const MIN_FIT_VERTICES = 5;

/** Measure.pts -> fit-shape wire points. VERIFIED basing (do not
 *  re-derive by guessing):
 *  - `routes/regions.py`'s `ProposeRegionResponse.points` docstring states
 *    its points are "normalized (x, y) pairs ... the same convention as
 *    ... Measure.pts" — and `RegionsCard.onDetect` below lands them via
 *    `res.points.map(([x, y]) => ({ x, y }))` with no offset, confirming
 *    `Measure.pts` is normalized `{x, y}` in [0, 1], x=column fraction,
 *    y=row fraction.
 *  - `lib/geometry.ts`'s `polygonStatsNormalized` denormalizes the exact
 *    same way this function does (`p.x * img.w, p.y * img.h`, no shift),
 *    landing in the app's ordinary 0-based image-pixel frame — the same
 *    frame `lib/api/core.ts`'s `measureProfile`/`measurePolyline`/
 *    `roiStats` already convert FROM when calling other 1-based backend
 *    endpoints (`[p.y + 1, p.x + 1]`).
 *  - `routes/shape_id.py`'s `FitShapeRequest.points` is documented
 *    `[[row, col], ...], px, 1-based` — the same target convention as
 *    those `core.ts` calls, so this mirrors their `+1` exactly.
 *  A basing slip here would be invisible in r/a/b/rms (the fits are
 *  translation-equivariant) and visible ONLY in the reported center —
 *  this is pinned by `measurePtsToFitPoints.test` asserting the exact
 *  `[[row, col]]` payload for known vertices. */
export function measurePtsToFitPoints(
  pts: { x: number; y: number }[],
  img: { w: number; h: number },
): [number, number][] {
  return pts.map(({ x, y }) => [y * img.h + 1, x * img.w + 1]);
}

/** A length (r, a, b, rms) in px -> the card's existing physical-units
 *  display convention: calibrated when the image has a pixel size, px
 *  otherwise (mirrors the area display below — `areaPhysical != null ? …
 *  unit … : … px …`). rms IS a length (a radial residual, same units as
 *  r/a/b) so it calibrates identically. */
function lengthDisplay(px: number, pixelSize: number | null, unit: string): string {
  return pixelSize != null
    ? `${Number((px * pixelSize).toPrecision(5))} ${unit}`
    : `${Number(px.toPrecision(5))} px`;
}

/** A fitted center (wire: 1-based `(cy, cx)`) -> the app's measure
 *  coordinate convention: 0-based image-pixel `(x, y)`, matching
 *  `lib/regionTable.ts`'s own `centroid`/`centroid_x_px`/`centroid_y_px`
 *  (derived straight from `polygonStats`, never offset). Centers are
 *  positions, not lengths, so — unlike r/a/b/rms — they are never
 *  calibrated: the app has no established convention for a calibrated
 *  ABSOLUTE position (only for differences/lengths, e.g. `physDist`),
 *  and the region table's own centroid columns are px-only for the same
 *  reason. */
function centerDisplay(cy: number, cx: number): string {
  const x = Number((cx - 1).toPrecision(6));
  const y = Number((cy - 1).toPrecision(6));
  return `(${x}, ${y}) px`;
}

/** wire `theta_rad` -> degrees for display. Convention (stated in the UI
 *  title, converted here from calc/shape_fit.py / diffraction_calib.py):
 *  measured from the image +col/x axis toward +row/y. */
function thetaDegrees(thetaRad: number): number {
  return Number(((thetaRad * 180) / Math.PI).toPrecision(4));
}

export default function RegionsCard() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const measures = useViewer((s) =>
    s.activeId ? (s.measures[s.activeId] ?? NO_MEASURES) : NO_MEASURES,
  );
  const addMeasure = useViewer((s) => s.addMeasure);
  const setStatus = useViewer((s) => s.setStatus);
  const [copyFlash, setCopyFlash] = useState(false);
  const [seedPct, setSeedPct] = useState({ x: 50, y: 50 });
  const [detecting, setDetecting] = useState(false);
  const [fits, setFits] = useState<Record<string, FitShapeResponse>>({});
  const [fittingId, setFittingId] = useState<string | null>(null);

  const rows = useMemo(
    () => (meta ? regionRows(measures, meta) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [measures, meta?.shape, meta?.pixel_size, meta?.pixel_unit],
  );

  if (!activeId || !meta || meta.kind === "spectrum") return null;

  const buildCsv = (): string =>
    tableToCsv(regionCsvColumns(meta), regionCsvRows(rows), {
      analysis: "Regions",
      imageName: meta.name,
    });

  const onExport = () => {
    downloadCsv(`${exportBaseName(meta.name)}_regions.csv`, buildCsv());
    setStatus(`exported ${rows.length} region(s) to CSV`);
  };

  const onCopy = () => {
    if (!navigator.clipboard?.writeText) {
      setStatus("clipboard unavailable — use Export CSV instead");
      return;
    }
    navigator.clipboard
      .writeText(buildCsv())
      .then(() => {
        setCopyFlash(true);
        setStatus(`copied ${rows.length} region(s) as CSV`);
        setTimeout(() => setCopyFlash(false), 1200);
      })
      .catch((e: Error) => setStatus(`copy failed: ${e.message}`));
  };

  const onDetect = () => {
    setDetecting(true);
    proposeRegion({
      image_id: activeId,
      seed: [seedPct.x / 100, seedPct.y / 100],
    })
      .then((res) => {
        addMeasure(activeId, {
          kind: "polygon",
          pts: res.points.map(([x, y]) => ({ x, y })),
        });
        setStatus(
          `detected region (${Number(res.area_px.toPrecision(5))} px²) — ` +
            "drag its vertices to correct",
        );
      })
      .catch((e: Error) => setStatus(`detect region failed: ${e.message}`))
      .finally(() => setDetecting(false));
  };

  const onFit = (measureId: string, pts: { x: number; y: number }[]) => {
    setFittingId(measureId);
    const img = { w: meta.shape[1] ?? 1, h: meta.shape[0] ?? 1 };
    fitShape({ points: measurePtsToFitPoints(pts, img) })
      .then((res) => {
        setFits((f) => ({ ...f, [measureId]: res }));
        setStatus(
          `fit region — circle rms ${lengthDisplay(res.circle.rms, meta.pixel_size, meta.pixel_unit)}, ` +
            `ellipse rms ${lengthDisplay(res.ellipse.rms, meta.pixel_size, meta.pixel_unit)}`,
        );
      })
      .catch((e: Error) => setStatus(`fit shape failed: ${e.message}`))
      .finally(() => setFittingId(null));
  };

  return (
    <Card title="Region Measurements" count={rows.length} defaultOpen={false}>
      <div className="fvd-ws-note">
        Polygon and lasso regions on this image, with area in physical units
        derived from the current calibration.
      </div>
      <div className="fvd-ws-row" style={{ alignItems: "center", gap: 6 }}>
        <span className="fvd-ws-note" style={{ margin: 0 }}>
          Seed
        </span>
        <label style={{ display: "flex", alignItems: "center", gap: 3 }}>
          X
          <input
            type="number"
            min={0}
            max={100}
            value={seedPct.x}
            onChange={(e) =>
              setSeedPct((s) => ({ ...s, x: Number(e.target.value) }))
            }
            style={{ width: 48 }}
          />
          %
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 3 }}>
          Y
          <input
            type="number"
            min={0}
            max={100}
            value={seedPct.y}
            onChange={(e) =>
              setSeedPct((s) => ({ ...s, y: Number(e.target.value) }))
            }
            style={{ width: 48 }}
          />
          %
        </label>
        <button
          className="fvd-btn"
          title="Propose a region outline from the seed point above (multi-Otsu + morphology) — lands as an ordinary polygon you can drag to correct"
          disabled={detecting}
          onClick={onDetect}
        >
          {detecting ? "Detecting…" : "Detect Region"}
        </button>
      </div>
      {rows.length === 0 ? (
        <div className="fvd-ws-note" style={{ color: "var(--fvd-muted)" }}>
          No regions drawn yet — draw a polygon or lasso region to populate
          this table.
        </div>
      ) : (
        <>
          <div className="fvd-measure-list" style={{ marginTop: 4 }}>
            {rows.map((r) => {
              const measure = measures.find((m) => m.id === r.measureId);
              const vertexCount = measure?.pts.length ?? 0;
              const canFit = vertexCount >= MIN_FIT_VERTICES;
              const fit = fits[r.measureId];
              // Stage label / MeasurePanel row / this card must never
              // disagree, so the same per-measure override converts this
              // on-screen area too. NOT applied to the CSV export below
              // (buildCsv/regionCsvRows) — that column's header names ONE
              // unit for the whole table (areaPhysicalColumn) and its
              // values feed regionPhysicalAreas' cross-image roll-up
              // (W4 item 24), both of which require every row to share one
              // unit; per-row overrides would corrupt that contract.
              const areaDisp =
                r.areaPhysical != null &&
                measure?.displayUnit &&
                displayArea(r.areaPhysical, meta.pixel_unit, measure.displayUnit);
              return (
                <div key={r.measureId}>
                  <div className="fvd-measure-row">
                    <span className="glyph">{r.kind === "lasso" ? "◈" : "⬠"}</span>
                    <span
                      className="name"
                      style={{
                        flex: 1,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={r.label}
                    >
                      {r.label}
                    </span>
                    <span
                      className="val"
                      title={`${r.areaPx2.toPrecision(5)} px² · perimeter ${r.perimeterPx.toPrecision(4)} px`}
                    >
                      {areaDisp
                        ? `${Number(areaDisp.value.toPrecision(5))} ${areaDisp.unit}`
                        : r.areaPhysical != null
                          ? `${Number(r.areaPhysical.toPrecision(5))} ${meta.pixel_unit}²`
                          : `${Number(r.areaPx2.toPrecision(5))} px²`}
                    </span>
                    <button
                      className="fvd-btn"
                      title={
                        canFit
                          ? "Fit a circle and an ellipse to this region's vertices (calc/shape_fit.py) — both shown below with their RMS residual; advisory, nothing auto-picked"
                          : `needs ≥ ${MIN_FIT_VERTICES} vertices to fit (has ${vertexCount}) — the ellipse fit alone needs ≥ 5 non-degenerate points, and a fit from fewer is not meaningful`
                      }
                      disabled={!canFit || fittingId === r.measureId}
                      onClick={() => measure && onFit(r.measureId, measure.pts)}
                    >
                      {fittingId === r.measureId ? "Fitting…" : "Fit"}
                    </button>
                  </div>
                  {fit && (
                    <div
                      className="fvd-ws-note"
                      style={{ marginLeft: 20, marginBottom: 4 }}
                    >
                      <div>
                        circle — center {centerDisplay(fit.circle.cy, fit.circle.cx)}, r{" "}
                        {lengthDisplay(fit.circle.r, meta.pixel_size, meta.pixel_unit)}, rms{" "}
                        {lengthDisplay(fit.circle.rms, meta.pixel_size, meta.pixel_unit)}
                      </div>
                      <div
                        title="θ measured from the image +x (column) axis toward +y (row), converted from the wire's theta_rad (radians)"
                      >
                        ellipse — center {centerDisplay(fit.ellipse.cy, fit.ellipse.cx)}, a{" "}
                        {lengthDisplay(fit.ellipse.a, meta.pixel_size, meta.pixel_unit)}, b{" "}
                        {lengthDisplay(fit.ellipse.b, meta.pixel_size, meta.pixel_unit)}, θ{" "}
                        {thetaDegrees(fit.ellipse.theta_rad)}° (+x→+y), rms{" "}
                        {lengthDisplay(fit.ellipse.rms, meta.pixel_size, meta.pixel_unit)}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <div className="fvd-ws-row">
            <button
              className="fvd-btn"
              title="Copy the region table to the clipboard as CSV"
              onClick={onCopy}
            >
              {copyFlash ? "Copied!" : "Copy CSV"}
            </button>
            <button
              className="fvd-btn"
              title="Download the region table as CSV"
              onClick={onExport}
            >
              Export CSV
            </button>
          </div>
        </>
      )}
    </Card>
  );
}
