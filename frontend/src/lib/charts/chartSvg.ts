// Generic vector (SVG) export for any uPlot-backed analysis chart
// (ANALYSIS_PRESENTATION_PLAN item 4 / audit R2). Built ONCE from uPlot's
// PUBLIC instance state (`u.series`, `u.data`, `u.scales`, `u.axes`,
// `u.root`, `u.width`, `u.height`) so every chart wrapped in
// PlotContextSurface gets vector + high-DPI export with zero per-chart
// wiring — no underscore-private uPlot field is read anywhere in this file.
//
// Two-step pipeline: `specFromUplot` reads a live instance into a plain,
// serialisable `ChartSpec`; `chartToSvg` renders that spec to an SVG string
// with no DOM/canvas dependency at all (so it's trivially unit-testable from
// a hand-built spec, independent of uPlot entirely). `svgToPngBlob` rasters
// the resulting SVG at a chosen DPI for a high-resolution PNG download.
//
// v1 HONESTY LIMITS (documented here per ANALYSIS_PRESENTATION_PLAN #4):
//   - Series polylines, axes, gridlines, tick labels, legend and title are
//     reproduced. Custom `hooks.draw` overlays are NOT — energy-window
//     shading (SpectrumPlot), error-bar caps (ResultVsParamPlot), interface
//     markers (LayersDepthPlot) etc. are canvas-only annotations with no
//     public uPlot representation to read back, so an exported chart can
//     look plainer than the live screen. ±σ shaded BANDS built by
//     lib/charts/sigmaBand.ts are the one exception explicitly excluded on
//     purpose: their hi/lo boundary series ARE public series, but v1 only
//     recognises and skips them (see `BAND_LEGEND_ROW_CLASS` below) rather
//     than reproducing the fill, so a banded chart exports its visible
//     lines correctly without a misleading partial band.
//   - Only the default "y" scale is exported. A chart using a second
//     (`y2`-style) scale key would have that series plotted against the
//     wrong range; no shipped chart does this today (grepped at authoring
//     time), so it is a documented gap rather than a handled case.
//   - Tick positions are recomputed from the public min/max range with a
//     standard 1-2-5 ladder (ticks.ts) rather than read from uPlot, which
//     computes its on-screen ticks from private internals. Labels will not
//     always land on the exact same values uPlot drew on screen.

import type uPlot from "uplot";

import { BAND_LEGEND_ROW_CLASS } from "./sigmaBand";
import { formatTickLabel, niceLogTicks, niceTicks } from "./ticks";

// ── spec types ──────────────────────────────────────────────────────────

export interface ChartSeriesSpec {
  label: string;
  /** CSS colour string, already resolved (no `var(--…)` references). */
  color: string;
  width: number;
  visible: boolean;
  /** y-values aligned with the spec's `x` array; `null` is a gap, matching
   *  uPlot's own convention (a null y breaks the line). */
  points: (number | null)[];
}

export interface ChartSpec {
  title?: string;
  /** Axis label, units baked in (e.g. "E (keV)") — matching this codebase's
   *  own uPlot series/axis label convention rather than a separate unit
   *  field. */
  xLabel?: string;
  yLabel?: string;
  x: number[];
  series: ChartSeriesSpec[];
  /** Explicit visible window; omitted ⇒ computed from data extents. */
  xRange?: [number, number];
  yRange?: [number, number];
  logX?: boolean;
  logY?: boolean;
  /** Physical CSS-pixel size of the exported SVG (96 dpi basis). Omitted ⇒
   *  chartToSvg's own defaults. */
  width?: number;
  height?: number;
}

// ── fixed publication palette + typography ────────────────────────────
//
// A chart export is print/journal output, not a screenshot of the app —
// so it uses a FIXED light "paper" palette regardless of the app's current
// theme, the same principle lib/elemental/figureExport.ts's renderFigure
// applies (a fixed background chosen for the medium, not read from the
// live theme). Line charts conventionally publish on white with dark ink,
// the opposite convention from that module's raster micrographs, which is
// why the exact colour differs — the fixed-regardless-of-theme PRINCIPLE is
// what's shared.

const FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', Arial, sans-serif";
const TITLE_SIZE = 16;
const AXIS_LABEL_SIZE = 12;
const TICK_LABEL_SIZE = 11;
const LEGEND_SIZE = 11;

const PAPER_BG = "#ffffff";
const AXIS_COLOR = "#333333";
const GRID_COLOR = "#dddddd";
const TEXT_COLOR = "#1a1a1a";
const DEFAULT_SERIES_COLOR = "#3b82f6";

/** Fallback physical size (96-dpi CSS px) when a spec/instance supplies
 *  none; also chartRaster.ts's fallback when parsing an SVG's own
 *  width/height attribute fails. */
export const DEFAULT_WIDTH = 720;
export const DEFAULT_HEIGHT = 420;
const MIN_WIDTH = 320;
const MIN_HEIGHT = 220;

// ── small geometry / text helpers ──────────────────────────────────────

function escapeXml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Rough glyph-width estimate for a sans-serif font, used only to size
 *  margins/legend wrapping — the SVG itself lets the renderer's real font
 *  metrics draw the text, so this never needs to be exact. */
function estimateTextWidth(text: string, fontSize: number): number {
  return text.length * fontSize * 0.56;
}

interface Domain {
  min: number;
  max: number;
}

function extentOf(
  values: readonly (number | null | undefined)[],
  positiveOnly: boolean,
): Domain | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v == null || !Number.isFinite(v)) continue;
    if (positiveOnly && v <= 0) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return Number.isFinite(lo) && Number.isFinite(hi) ? { min: lo, max: hi } : null;
}

function xExtent(x: readonly number[], log: boolean): Domain {
  return extentOf(x, log) ?? (log ? { min: 1, max: 10 } : { min: 0, max: 1 });
}

function yExtent(series: readonly ChartSeriesSpec[], log: boolean): Domain {
  const visible = series.filter((s) => s.visible);
  const all: (number | null | undefined)[] = [];
  for (const s of visible) all.push(...s.points);
  return extentOf(all, log) ?? (log ? { min: 1, max: 10 } : { min: 0, max: 1 });
}

/** Linear or log10 map from a data domain to a pixel range. `range` is
 *  given as [valueAtDomainMin, valueAtDomainMax] in pixel space, so the
 *  caller supplies [bottom, top] for a y-axis to get the usual "up is
 *  bigger" orientation without a separate invert flag. */
function makeScale(
  domain: Domain,
  range: [number, number],
  log: boolean,
): (v: number) => number {
  const [r0, r1] = range;
  if (log) {
    const lo = Math.log10(domain.min);
    const hi = Math.log10(domain.max);
    const span = hi - lo || 1;
    return (v: number) => r0 + ((Math.log10(v) - lo) / span) * (r1 - r0);
  }
  const span = domain.max - domain.min || 1;
  return (v: number) => r0 + ((v - domain.min) / span) * (r1 - r0);
}

/** One `<path>` `d` string per series, breaking into a fresh `M` subpath at
 *  every gap (null/non-finite y, or a non-positive value on a log axis —
 *  matching uPlot's own "a null y breaks the line" convention). */
function seriesPathD(
  xs: readonly number[],
  ys: readonly (number | null | undefined)[],
  xScale: (v: number) => number,
  yScale: (v: number) => number,
  logX: boolean,
  logY: boolean,
): string {
  const segments: string[] = [];
  let open = false;
  for (let i = 0; i < xs.length; i++) {
    const xv = xs[i];
    const yv = ys[i];
    const valid =
      xv != null &&
      Number.isFinite(xv) &&
      (!logX || xv > 0) &&
      yv != null &&
      Number.isFinite(yv) &&
      (!logY || yv > 0);
    if (!valid) {
      open = false;
      continue;
    }
    const px = xScale(xv).toFixed(2);
    const py = yScale(yv).toFixed(2);
    segments.push(`${open ? "L" : "M"} ${px} ${py}`);
    open = true;
  }
  return segments.join(" ");
}

/** Wrap legend chips into rows that fit `maxWidth`, in series order. */
function layoutLegendRows(
  series: readonly ChartSeriesSpec[],
  maxWidth: number,
): ChartSeriesSpec[][] {
  const rows: ChartSeriesSpec[][] = [[]];
  let rowWidth = 0;
  for (const s of series) {
    const itemWidth = 16 + 6 + estimateTextWidth(s.label, LEGEND_SIZE) + 18;
    const row = rows[rows.length - 1];
    if (rowWidth + itemWidth > maxWidth && row.length > 0) {
      rows.push([]);
      rowWidth = 0;
    }
    rows[rows.length - 1].push(s);
    rowWidth += itemWidth;
  }
  return rows;
}

// ── rendering ───────────────────────────────────────────────────────────

/**
 * Render a ChartSpec to a standalone, self-contained SVG string: axes,
 * gridlines, tick labels, series polylines (visible series only), a legend
 * of visible series, and a title. Pure — no DOM, no canvas — so it runs
 * identically in a browser or a test.
 */
export function chartToSvg(spec: ChartSpec): string {
  const width = Math.max(MIN_WIDTH, Math.round(spec.width ?? DEFAULT_WIDTH));
  const height = Math.max(MIN_HEIGHT, Math.round(spec.height ?? DEFAULT_HEIGHT));
  const logX = !!spec.logX;
  const logY = !!spec.logY;

  const xDomain = spec.xRange
    ? { min: spec.xRange[0], max: spec.xRange[1] }
    : xExtent(spec.x, logX);
  const yDomain = spec.yRange
    ? { min: spec.yRange[0], max: spec.yRange[1] }
    : yExtent(spec.series, logY);

  const xTicks = (logX ? niceLogTicks(xDomain.min, xDomain.max) : niceTicks(xDomain.min, xDomain.max))
    .filter((t) => t >= Math.min(xDomain.min, xDomain.max) && t <= Math.max(xDomain.min, xDomain.max));
  const yTicks = (logY ? niceLogTicks(yDomain.min, yDomain.max) : niceTicks(yDomain.min, yDomain.max))
    .filter((t) => t >= Math.min(yDomain.min, yDomain.max) && t <= Math.max(yDomain.min, yDomain.max));

  const yTickWidth = Math.max(
    12,
    ...yTicks.map((t) => estimateTextWidth(formatTickLabel(t), TICK_LABEL_SIZE)),
  );

  const visibleSeries = spec.series.filter((s) => s.visible);
  const legendRows = visibleSeries.length ? layoutLegendRows(visibleSeries, width - 32) : [];
  const legendH = legendRows.length ? legendRows.length * 18 + 8 : 0;

  const titleH = spec.title ? TITLE_SIZE + 14 : 8;
  const marginLeft = 8 + yTickWidth + 6 + (spec.yLabel ? AXIS_LABEL_SIZE + 8 : 0);
  const marginRight = 20;
  const marginTop = titleH;
  const marginBottom =
    8 + TICK_LABEL_SIZE + 6 + (spec.xLabel ? AXIS_LABEL_SIZE + 8 : 0) + legendH;

  const plot = {
    x: marginLeft,
    y: marginTop,
    w: Math.max(10, width - marginLeft - marginRight),
    h: Math.max(10, height - marginTop - marginBottom),
  };

  const xScale = makeScale(xDomain, [plot.x, plot.x + plot.w], logX);
  const yScale = makeScale(yDomain, [plot.y + plot.h, plot.y], logY);

  const parts: string[] = [];
  parts.push(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" ` +
      `viewBox="0 0 ${width} ${height}" font-family="${FONT_FAMILY}">`,
  );
  parts.push(`<rect x="0" y="0" width="${width}" height="${height}" fill="${PAPER_BG}"/>`);

  if (spec.title) {
    parts.push(
      `<text x="${width / 2}" y="${TITLE_SIZE + 8}" text-anchor="middle" ` +
        `font-size="${TITLE_SIZE}" font-weight="600" fill="${TEXT_COLOR}">` +
        `${escapeXml(spec.title)}</text>`,
    );
  }

  for (const t of xTicks) {
    const px = xScale(t).toFixed(2);
    parts.push(
      `<line x1="${px}" y1="${plot.y}" x2="${px}" y2="${plot.y + plot.h}" ` +
        `stroke="${GRID_COLOR}" stroke-width="1"/>`,
    );
    parts.push(
      `<line x1="${px}" y1="${plot.y + plot.h}" x2="${px}" y2="${plot.y + plot.h + 5}" ` +
        `stroke="${AXIS_COLOR}" stroke-width="1"/>`,
    );
    parts.push(
      `<text x="${px}" y="${plot.y + plot.h + 5 + TICK_LABEL_SIZE + 2}" text-anchor="middle" ` +
        `font-size="${TICK_LABEL_SIZE}" fill="${TEXT_COLOR}">${escapeXml(formatTickLabel(t))}</text>`,
    );
  }
  for (const t of yTicks) {
    const py = yScale(t).toFixed(2);
    parts.push(
      `<line x1="${plot.x}" y1="${py}" x2="${plot.x + plot.w}" y2="${py}" ` +
        `stroke="${GRID_COLOR}" stroke-width="1"/>`,
    );
    parts.push(
      `<line x1="${plot.x - 5}" y1="${py}" x2="${plot.x}" y2="${py}" ` +
        `stroke="${AXIS_COLOR}" stroke-width="1"/>`,
    );
    parts.push(
      `<text x="${plot.x - 8}" y="${Number(py) + TICK_LABEL_SIZE / 2 - 1}" text-anchor="end" ` +
        `font-size="${TICK_LABEL_SIZE}" fill="${TEXT_COLOR}">${escapeXml(formatTickLabel(t))}</text>`,
    );
  }

  parts.push(
    `<rect x="${plot.x}" y="${plot.y}" width="${plot.w}" height="${plot.h}" ` +
      `fill="none" stroke="${AXIS_COLOR}" stroke-width="1"/>`,
  );

  if (spec.xLabel) {
    parts.push(
      `<text x="${plot.x + plot.w / 2}" y="${height - legendH - 6}" text-anchor="middle" ` +
        `font-size="${AXIS_LABEL_SIZE}" fill="${TEXT_COLOR}">${escapeXml(spec.xLabel)}</text>`,
    );
  }
  if (spec.yLabel) {
    const cy = plot.y + plot.h / 2;
    parts.push(
      `<text x="14" y="${cy}" text-anchor="middle" font-size="${AXIS_LABEL_SIZE}" ` +
        `fill="${TEXT_COLOR}" transform="rotate(-90 14 ${cy})">${escapeXml(spec.yLabel)}</text>`,
    );
  }

  for (const s of spec.series) {
    if (!s.visible) continue;
    const d = seriesPathD(spec.x, s.points, xScale, yScale, logX, logY);
    if (!d) continue;
    parts.push(
      `<path d="${d}" fill="none" stroke="${s.color || DEFAULT_SERIES_COLOR}" ` +
        `stroke-width="${s.width || 1.5}" stroke-linejoin="round" stroke-linecap="round"/>`,
    );
  }

  if (legendRows.length) {
    let ly = height - legendRows.length * 18 - 2;
    for (const row of legendRows) {
      let lx = 16;
      for (const s of row) {
        parts.push(
          `<rect x="${lx}" y="${ly - 10}" width="12" height="12" fill="${s.color || DEFAULT_SERIES_COLOR}"/>`,
        );
        parts.push(
          `<text x="${lx + 18}" y="${ly}" font-size="${LEGEND_SIZE}" fill="${TEXT_COLOR}">` +
            `${escapeXml(s.label)}</text>`,
        );
        lx += 16 + 6 + estimateTextWidth(s.label, LEGEND_SIZE) + 18;
      }
      ly += 18;
    }
  }

  parts.push(`</svg>`);
  return parts.join("");
}

// ── build a spec from a live uPlot instance ────────────────────────────

export interface SpecFromUplotOptions {
  /** Not derivable from the instance (uPlot's `title` option isn't exposed
   *  as an instance field) — the caller supplies it, typically the same
   *  `label` PlotContextSurface already carries. */
  title: string;
  xLabel?: string;
  yLabel?: string;
  width?: number;
  height?: number;
}

function inferStringLabel(label: unknown): string | undefined {
  return typeof label === "string" && label ? label : undefined;
}

/** Resolve a series' stroke to a plain CSS colour string: call it if it's a
 *  uPlot per-series colour function (public API — `(self, seriesIdx) =>
 *  strokeStyle`), and resolve a `var(--token)` reference against the plot
 *  root's CURRENT computed style so the export matches what was on screen
 *  rather than the raw, unresolved token string. */
function resolveSeriesColor(
  stroke: unknown,
  u: uPlot,
  seriesIdx: number,
  root: Element | null,
): string {
  const raw =
    typeof stroke === "function"
      ? (stroke as (self: uPlot, i: number) => unknown)(u, seriesIdx)
      : stroke;
  if (typeof raw !== "string" || !raw) return DEFAULT_SERIES_COLOR;
  const varMatch = /^var\((--[\w-]+)/.exec(raw.trim());
  if (varMatch && root && typeof getComputedStyle === "function") {
    const resolved = getComputedStyle(root).getPropertyValue(varMatch[1]).trim();
    if (resolved) return resolved;
  }
  return raw;
}

/**
 * Build a ChartSpec from a LIVE uPlot instance, reading only public state:
 * `u.series` (label/stroke/width/show), `u.data` (x + each series' y),
 * `u.scales` (current min/max + `distr` for log detection) and `u.axes`
 * (axis label text, when the chart set one). No underscore-private field is
 * touched.
 *
 * Band boundary series (lib/charts/sigmaBand.ts, marked with
 * `BAND_LEGEND_ROW_CLASS`) are recognised and dropped — see this module's
 * header for why v1 doesn't reproduce the shaded fill.
 */
export function specFromUplot(u: uPlot, opts: SpecFromUplotOptions): ChartSpec {
  const rawSeries = u.series ?? [];
  const rawData = u.data ?? [];
  const xData = (rawData[0] ?? []) as readonly (number | null | undefined)[];
  const x = xData.map((v) => (v == null ? Number.NaN : Number(v)));

  const series: ChartSeriesSpec[] = [];
  for (let i = 1; i < rawSeries.length; i++) {
    const s = rawSeries[i];
    if (s.class === BAND_LEGEND_ROW_CLASS) continue;
    const rawPoints = (rawData[i] ?? []) as readonly (number | null | undefined)[];
    series.push({
      label: inferStringLabel(s.label) ?? `series ${i}`,
      color: resolveSeriesColor(s.stroke, u, i, u.root ?? null),
      width: typeof s.width === "number" ? s.width : 1,
      visible: s.show !== false,
      points: rawPoints.map((v) => (v == null || !Number.isFinite(v) ? null : Number(v))),
    });
  }

  const scaleX = u.scales?.x;
  const scaleY = u.scales?.y;
  const xRange: [number, number] | undefined =
    scaleX?.min != null && scaleX?.max != null ? [scaleX.min, scaleX.max] : undefined;
  const yRange: [number, number] | undefined =
    scaleY?.min != null && scaleY?.max != null ? [scaleY.min, scaleY.max] : undefined;

  const visible = series.filter((s) => s.visible);
  const xLabel =
    opts.xLabel ?? inferStringLabel(u.axes?.[0]?.label) ?? inferStringLabel(rawSeries[0]?.label);
  const yLabel =
    opts.yLabel ??
    inferStringLabel(u.axes?.[1]?.label) ??
    (visible.length === 1 ? visible[0].label : undefined);

  return {
    title: opts.title,
    xLabel,
    yLabel,
    x,
    series,
    xRange,
    yRange,
    logX: scaleX?.distr === 3,
    logY: scaleY?.distr === 3,
    width: opts.width ?? u.width,
    height: opts.height ?? u.height,
  };
}

// High-resolution PNG rasterisation (svgToPngBlob) lives in chartRaster.ts —
// split out to keep this module under the repo's 500-line ceiling, and
// because it's the one piece of this pipeline that needs a real browser
// Image/canvas (see that file's header for why it isn't unit-tested here).
