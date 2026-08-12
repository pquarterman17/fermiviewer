// Population histogram + fitted-distribution overlay for measured object
// populations (particle equivalent diameters, grain diameters — was audit
// R6, ANALYSIS_PRESENTATION_PLAN.md #6). Population-agnostic: any workshop
// with a list of per-object size-like values drops this in with a unit
// label. "The one JMP-shaped feature squarely in-mission" — a size
// histogram with a normal/log-normal/Weibull overlay and a readable
// summary (N, mean ± std, median [q1, q3]), the artifact a paper figure
// or a lab notebook actually wants.
//
// Fetches summary+histogram+fits ONCE per `values` array via
// POST /api/analyze/distribution (fit="all") and lets the distribution
// SELECTOR switch which already-fetched curve is drawn client-side — no
// re-request per dropdown change (see lib/api/distributions.ts). A
// population below the backend's MIN_FIT_N (too few objects to fit)
// falls back to a histogram-only request (fit="none") instead of
// failing outright — the histogram/summary are still useful on their own.
//
// Chart: uPlot's built-in bars path renderer draws the histogram bars
// (bin centers as x, matching calc/distributions.histogram_bins' uniform
// edges); the fitted-pdf curve is drawn on top via a `hooks.draw` overlay
// at its own resolution (the established pattern for anything uPlot
// doesn't render natively — see EelsFitResidualPlot's zero-baseline and
// ResultVsParamPlot's error bars) rather than forced onto the same,
// coarser bin-center x-array. `lib/populationHistogram.ts`'s
// `scaledPdfCurve` is what makes that curve's height comparable to the
// bars: pdf(x) * N * binWidth, not the raw pdf.

import { useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";

import {
  analyzeDistribution,
  type DistFit,
  type DistributionKind,
  type DistributionResult,
} from "../../lib/api";
import {
  binCenters,
  formatPopulationSummary,
  meanBinWidth,
  scaledPdfCurve,
} from "../../lib/populationHistogram";
import PlotContextSurface from "../plots/PlotContextSurface";

const HEIGHT = 200;
const CURVE_POINTS = 200;

type Selection = "best" | DistributionKind;

const SELECT_OPTIONS: { value: Selection; label: string }[] = [
  { value: "best", label: "Best" },
  { value: "normal", label: "Normal" },
  { value: "lognormal", label: "Log-normal" },
  { value: "weibull", label: "Weibull" },
];

function pickFit(result: DistributionResult | null, selection: Selection): DistFit | null {
  const fits = result?.fits;
  if (!fits) return null;
  const kind = selection === "best" ? fits.best : selection;
  return kind ? fits[kind] : null;
}

export default function PopulationHistogram({
  values,
  unit,
  title = "Size distribution",
  filename = "population_histogram.png",
}: {
  values: number[];
  unit: string;
  title?: string;
  filename?: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const [result, setResult] = useState<DistributionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection>("best");
  // a fresh array reference every render (e.g. from a `.map()` upstream)
  // must not retrigger the fetch — key on the actual numeric content
  const key = useMemo(() => values.join(","), [values]);

  useEffect(() => {
    let stale = false;
    setError(null);
    setResult(null);
    setSelection("best");
    if (values.length === 0) return;
    analyzeDistribution(values, "all")
      .then((r) => {
        if (!stale) setResult(r);
      })
      .catch(() => {
        // too few objects to fit (< calc.distributions.MIN_FIT_N), or a
        // population lognormal/weibull can't fit — the histogram and
        // summary are still useful on their own
        analyzeDistribution(values, "none")
          .then((r) => {
            if (!stale) setResult(r);
          })
          .catch((e: Error) => {
            if (!stale) setError(e.message);
          });
      });
    return () => {
      stale = true;
    };
    // `values` is intentionally represented by `key` (see above)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const fit = pickFit(result, selection);

  useEffect(() => {
    const host = hostRef.current;
    plotRef.current?.destroy();
    plotRef.current = null;
    if (!host || !result || result.histogram.counts.length === 0) return;

    const { histogram, summary } = result;
    const centers = binCenters(histogram);
    const counts = histogram.counts;
    const lo = histogram.edges[0];
    const hi = histogram.edges[histogram.edges.length - 1];
    const binWidth = meanBinWidth(histogram);
    const curve = fit
      ? scaledPdfCurve(fit, lo, hi, summary.n, binWidth, CURVE_POINTS)
      : null;
    const yMax = Math.max(1, ...counts, ...(curve ? curve.y : [0])) * 1.1;

    const style = getComputedStyle(document.documentElement);
    const accent = style.getPropertyValue("--accent").trim() || "#a78bfa";
    const barFill = style.getPropertyValue("--capture").trim() || "#38bdf8";
    const barsPath = uPlot.paths.bars;

    const u = new uPlot(
      {
        width: host.clientWidth || 300,
        height: HEIGHT,
        scales: {
          x: { time: false, range: () => [lo, hi] },
          y: { range: () => [0, yMax] },
        },
        series: [
          {},
          {
            label: "count",
            paths: barsPath ? barsPath({ size: [0.92], align: 0 }) : undefined,
            fill: barFill,
            stroke: barFill,
            width: 1,
            points: { show: false },
          },
        ],
        axes: [
          {
            stroke: "#888",
            grid: { stroke: "rgba(128,128,128,0.15)" },
            label: unit || "px",
          },
          {
            stroke: "#888",
            grid: { stroke: "rgba(128,128,128,0.15)" },
            label: "count",
            size: 44,
          },
        ],
        legend: { show: false },
        cursor: { y: false },
        hooks: {
          draw: curve
            ? [
                (u2) => {
                  const ctx = u2.ctx;
                  ctx.save();
                  ctx.strokeStyle = accent;
                  ctx.lineWidth = 1.75;
                  ctx.beginPath();
                  for (let i = 0; i < curve.x.length; i++) {
                    const px = u2.valToPos(curve.x[i], "x", true);
                    const py = u2.valToPos(curve.y[i], "y", true);
                    if (i === 0) ctx.moveTo(px, py);
                    else ctx.lineTo(px, py);
                  }
                  ctx.stroke();
                  ctx.restore();
                },
              ]
            : [],
        },
      },
      [centers, counts] as uPlot.AlignedData,
      host,
    );
    plotRef.current = u;
    const ro = new ResizeObserver(() => {
      if (plotRef.current && host.clientWidth > 0) {
        plotRef.current.setSize({ width: host.clientWidth, height: HEIGHT });
      }
    });
    ro.observe(host);
    return () => {
      ro.disconnect();
      u.destroy();
      plotRef.current = null;
    };
  }, [result, fit, unit]);

  if (values.length === 0) {
    return <div className="fvd-ws-note">No values to summarize.</div>;
  }
  if (error) {
    return <div className="fvd-ws-note">distribution: {error}</div>;
  }
  if (!result) {
    return <div className="fvd-ws-note">Loading distribution…</div>;
  }

  return (
    <>
      <div className="fvd-ws-row">
        <span className="k">fit</span>
        <select
          aria-label="Distribution"
          value={selection}
          disabled={!result.fits}
          onChange={(e) => setSelection(e.target.value as Selection)}
        >
          {SELECT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        {fit && (
          <span className="k">
            AIC {fit.aic.toFixed(1)} · KS p={fit.ks_pvalue.toFixed(3)}
          </span>
        )}
        {!result.fits && (
          <span className="k">too few objects to fit a distribution</span>
        )}
      </div>
      <PlotContextSurface
        ref={hostRef}
        plotRef={plotRef}
        label={title}
        filename={filename}
        className="fvd-ws-plot"
      />
      <div className="fvd-ws-note">
        {formatPopulationSummary(result.summary, unit)}
      </div>
    </>
  );
}
