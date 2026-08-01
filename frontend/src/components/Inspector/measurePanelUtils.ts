// MeasurePanel constants and pure helpers: kind glyphs, overlay-style
// option lists, and the log/histogram/stats builders that feed the
// Results window. Split out of MeasurePanel.tsx (repo-health #33).

import {
  physAngle,
  physDist,
  tiltDist,
  type TiltSettings,
} from "../../lib/geometry";
import { useStageInfo } from "../../store/stage";
import {
  useViewer,
  type EndSymbol,
  type Measure,
  type OverlayStyle,
} from "../../store/viewer";
import { useResults } from "../overlays/ResultsWindow";

export const KIND_GLYPH: Record<Measure["kind"], string> = {
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

export const SIZES: OverlayStyle["size"][] = ["XS", "S", "M", "L", "XL", "XXL"];
export const LINE_WIDTHS = [1, 1.5, 2, 2.5, 3, 4];
export const SWATCHES = ["#ffffff", "#22d3ee", "#fbbf24", "#f472b6", "#a3e635"];
export const END_SYMBOLS: { sym: EndSymbol; label: string }[] = [
  { sym: "bar", label: "|" },
  { sym: "none", label: "—" },
  { sym: "circle", label: "○" },
  { sym: "square", label: "□" },
  { sym: "cross", label: "×" },
];

// stable empty result — fresh [] per snapshot loops React (#185)
export const NO_MEASURES: Measure[] = [];

type MetaLike = {
  pixel_size: number | null;
  pixel_unit: string;
} | null;

/** Distance values (calibrated when possible) from line-like measures.
 *  Applies the per-image tilt correction (#34) when active so stats
 *  match the on-screen labels. */
export function distanceValues(
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

export function showLog(
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
      ...px
        .slice(0, 2)
        .flatMap((p) => [Number(p.x.toFixed(2)), Number(p.y.toFixed(2))]),
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
export function showRoiHistogram(m: Measure, img: { w: number; h: number }): void {
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

export function showStats(
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
