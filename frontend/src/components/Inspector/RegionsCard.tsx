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

import { useMemo, useState } from "react";

import { proposeRegion } from "../../lib/api/regions";
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

  return (
    <Card title="Regions" count={rows.length} defaultOpen={false}>
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
            {rows.map((r) => (
              <div key={r.measureId} className="fvd-measure-row">
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
                  {r.areaPhysical != null
                    ? `${Number(r.areaPhysical.toPrecision(5))} ${meta.pixel_unit}²`
                    : `${Number(r.areaPx2.toPrecision(5))} px²`}
                </span>
              </div>
            ))}
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
