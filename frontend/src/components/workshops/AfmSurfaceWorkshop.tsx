import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  afmSurface,
  ISO_PARAMS,
  type AfmLevel,
  type AfmSurfaceResult,
  type IsoParam,
} from "../../lib/api";
import { useAnalysisRoi } from "../../hooks/useAnalysisRoi";
import {
  downloadCsv,
  downloadJson,
  exportBaseName,
  tableToCsv,
  tableToJson,
  type Cell,
} from "../../lib/resultsExport";
import { useViewer } from "../../store/viewer";
import AnalysisRegionSelect from "./AnalysisRegionSelect";
import PlotContextSurface from "../plots/PlotContextSurface";

const NO_SHAPE: number[] = [];

/** ISO 25178-2 parameter families, in the order the standard lists them. */
export const ISO_GROUPS: { title: string; keys: IsoParam[] }[] = [
  { title: "Height", keys: ["Sa", "Sq", "Ssk", "Sku", "Sp", "Sv", "Sz"] },
  { title: "Hybrid", keys: ["Sdq", "Sdr"] },
  { title: "Spatial", keys: ["Sal", "Str", "Std"] },
];

const DESCRIPTIONS: Record<IsoParam, string> = {
  Sa: "arithmetic mean height",
  Sq: "root-mean-square height",
  Ssk: "skewness",
  Sku: "kurtosis",
  Sp: "maximum peak height",
  Sv: "maximum pit depth",
  Sz: "maximum height (Sp + Sv)",
  Sdq: "root-mean-square gradient",
  Sdr: "developed interfacial area ratio",
  Sal: "autocorrelation length (s = 0.2)",
  Str: "texture aspect ratio",
  Std: "texture direction (from +x, counter-clockwise)",
};

export function surfaceRows(result: AfmSurfaceResult): Cell[][] {
  return ISO_PARAMS.map((key) => [
    key,
    result.params[key],
    result.units[key],
    DESCRIPTIONS[key],
  ]);
}

export function formatParam(value: number | null, unit: string): string {
  if (value === null || !Number.isFinite(value)) return "—";
  const v =
    Math.abs(value) >= 1e4 || (value !== 0 && Math.abs(value) < 1e-3)
      ? value.toExponential(3)
      : value.toPrecision(4);
  return unit ? `${v} ${unit}` : v;
}

export default function AfmSurfaceWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) => (s.activeId ? (s.images[s.activeId] ?? null) : null));
  const setStatus = useViewer((s) => s.setStatus);
  const region = useAnalysisRoi(activeId, meta?.shape ?? NO_SHAPE);
  const [level, setLevel] = useState<AfmLevel>("plane");
  const [result, setResult] = useState<AfmSurfaceResult | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => setResult(null), [activeId]);

  const run = () => {
    if (!activeId) return;
    setBusy(true);
    setStatus("surface analysis…");
    afmSurface(activeId, { level, roi: region.roi })
      .then((next) => {
        setResult(next);
        setStatus(`surface: Sa ${formatParam(next.params.Sa, next.z_unit)} · ` +
          `Sq ${formatParam(next.params.Sq, next.z_unit)}`);
      })
      .catch((e: Error) => setStatus(`surface analysis: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const exportResult = (format: "csv" | "json") => {
    if (!result) return;
    const base = `${exportBaseName(meta?.name)}_iso25178`;
    const columns = ["parameter", "value", "unit", "description"];
    const provenance = {
      analysis: "Areal surface texture (ISO 25178)",
      imageName: meta?.name,
      params: { level: result.level, region: region.label, roi: result.roi },
    };
    if (format === "csv") {
      downloadCsv(`${base}.csv`, tableToCsv(columns, surfaceRows(result), provenance));
    } else {
      downloadJson(`${base}.json`, tableToJson(columns, surfaceRows(result), provenance));
    }
  };

  if (!meta || meta.kind !== "image") {
    return <div className="fvd-ws-empty">Select a 2D height map.</div>;
  }

  return (
    <div className="fvd-ws">
      <AnalysisRegionSelect
        choice={region.choice}
        imageId={activeId}
        roi={region.roi}
        options={region.options}
        disabled={busy}
        onChange={region.setChoice}
      />
      <div className="fvd-ws-row">
        <label className="k" htmlFor="afm-surface-level">Level</label>
        <select
          id="afm-surface-level"
          value={level}
          disabled={busy}
          onChange={(e) => setLevel(e.target.value as AfmLevel)}
        >
          <option value="none">None (already levelled)</option>
          <option value="plane">Plane</option>
          <option value="quadratic">Quadratic</option>
        </select>
        <button className="fvd-btn primary" disabled={busy} onClick={run}>
          {busy ? "Analyzing…" : "Analyze"}
        </button>
      </div>

      {result && (
        <>
          {ISO_GROUPS.map((group) => (
            <section key={group.title}>
              <div className="fvd-ws-note">{group.title}</div>
              <div className="fvd-metrics">
                {group.keys.map((key) => (
                  <div className="fvd-metric" key={key} title={DESCRIPTIONS[key]}>
                    <span className="v">{formatParam(result.params[key], result.units[key])}</span>
                    <span className="k">{key}</span>
                  </div>
                ))}
              </div>
            </section>
          ))}
          {!result.slopes_calibrated && (
            <div className="fvd-ws-note">
              Sdq, Sdr and slopes need heights and pixel size in length units.
            </div>
          )}
          <CurvePlot
            title="Radial power spectral density"
            x={result.psd.frequency}
            y={result.psd.power}
            xLabel={`spatial frequency (1/${result.lateral_unit})`}
            yLabel={`PSD (${result.z_unit}²·${result.lateral_unit}²)`}
            log
          />
          <CurvePlot
            title="Height distribution"
            x={result.height_hist.height}
            y={result.height_hist.percent}
            xLabel={`height (${result.z_unit})`}
            yLabel="% of pixels"
          />
          {result.slope_hist.angle.length > 0 && (
            <CurvePlot
              title="Slope distribution"
              x={result.slope_hist.angle}
              y={result.slope_hist.percent}
              xLabel="slope (°)"
              yLabel="% of pixels"
            />
          )}
          <div className="fvd-ws-note">
            {result.n_pixels.toLocaleString()} valid pixels · {region.label} ·{" "}
            {result.level} levelling
          </div>
          <div className="fvd-ws-row">
            <button className="fvd-btn" onClick={() => exportResult("csv")}>Export CSV</button>
            <button className="fvd-btn" onClick={() => exportResult("json")}>Export JSON</button>
          </div>
        </>
      )}
    </div>
  );
}

function CurvePlot({
  title, x, y, xLabel, yLabel, log = false,
}: {
  title: string;
  x: number[];
  y: number[];
  xLabel: string;
  yLabel: string;
  log?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => {
    const element = host.current;
    // a log axis cannot show zero or negative values
    const keep = x.map((_, i) => !log || (x[i] > 0 && y[i] > 0));
    const xs = x.filter((_, i) => keep[i]);
    const ys = y.filter((_, i) => keep[i]);
    if (!element || xs.length < 2) return;
    const accent =
      getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() ||
      "#7c5ce7";
    plotRef.current = new uPlot(
      {
        width: element.clientWidth || 560,
        height: 170,
        scales: { x: { time: false, distr: log ? 3 : 1 }, y: { distr: log ? 3 : 1 } },
        series: [{}, { label: yLabel, stroke: accent, width: 1.5 }],
        axes: [
          { label: xLabel, stroke: "#888" },
          { label: yLabel, stroke: "#888" },
        ],
        legend: { show: false },
        cursor: { y: false },
      },
      [xs, ys],
      element,
    );
    return () => {
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [x, y, xLabel, yLabel, log]);

  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return (
    <section>
      <div className="fvd-ws-note">{title}</div>
      <PlotContextSurface
        ref={host}
        plotRef={plotRef}
        label={title}
        filename={`${slug}.png`}
        className="fvd-ws-plot"
      />
    </section>
  );
}
