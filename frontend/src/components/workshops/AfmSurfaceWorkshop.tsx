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
import { heightAnalysisKey } from "../../lib/analysisFreshness";
import { useViewer } from "../../store/viewer";
import AnalysisRegionSelect from "./AnalysisRegionSelect";
import PlotContextSurface from "../plots/PlotContextSurface";

const NO_SHAPE: number[] = [];
const SUMMARY_PARAMS: IsoParam[] = ["Sq", "Sa", "Sz", "Ssk", "Sal"];
type SurfacePlot = "psd" | "height" | "slope";

/** ISO 25178-2 parameter families, in the order the standard lists them. */
export const ISO_GROUPS: { title: string; keys: IsoParam[] }[] = [
  { title: "Height", keys: ["Sa", "Sq", "Ssk", "Sku", "Sp", "Sv", "Sz"] },
  { title: "Hybrid", keys: ["Sdq", "Sdr"] },
  { title: "Spatial", keys: ["Sal", "Str", "Std"] },
  { title: "Functional", keys: ["Sk", "Spk", "Svk", "Smr1", "Smr2", "Vmp", "Vmc", "Vvc", "Vvv"] },
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
  Sk: "core height",
  Spk: "reduced peak height",
  Svk: "reduced valley depth",
  Smr1: "peak material ratio (top of the core)",
  Smr2: "valley material ratio (bottom of the core)",
  Vmp: "peak material volume (mr = 10 %), per area",
  Vmc: "core material volume (10–80 %), per area",
  Vvc: "core void volume (10–80 %), per area",
  Vvv: "valley void volume (mr = 80 %), per area",
};

const SUMMARY_NAMES: Partial<Record<IsoParam, string>> = {
  Sq: "Area RMS roughness",
  Sa: "Area average roughness",
  Sz: "Maximum surface height",
  Ssk: "Surface skewness",
  Sal: "Autocorrelation length",
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
  // the region the result was measured on, not the one selected now
  const [resultRegion, setResultRegion] = useState("");
  const [resultKey, setResultKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [activePlot, setActivePlot] = useState<SurfacePlot>("psd");
  const [openGroups, setOpenGroups] = useState<string[]>(["Height"]);
  const controlKey = heightAnalysisKey(region.choice, region.roi, level);
  const resultStale = result !== null && resultKey !== controlKey;

  // Each run gets a number; switching image or closing the panel bumps it,
  // so a request still in flight for the previous image is ignored when it
  // lands instead of filling the panel with that image's numbers.
  const request = useRef(0);
  useEffect(() => {
    request.current += 1;
    setResult(null);
    setBusy(false);
  }, [activeId]);
  useEffect(() => () => {
    request.current += 1;
  }, []);

  const run = () => {
    if (!activeId) return;
    const runRegion = region.label;
    const token = ++request.current;
    const current = () => token === request.current;
    setBusy(true);
    setStatus("surface analysis…");
    afmSurface(activeId, { level, roi: region.roi })
      .then((next) => {
        if (!current()) return;
        setActivePlot((plot) => (
          plot === "slope" && next.slope_hist.angle.length === 0 ? "psd" : plot
        ));
        setResult(next);
        setResultRegion(runRegion);
        setResultKey(controlKey);
        setStatus(`surface: Sa ${formatParam(next.params.Sa, next.z_unit)} · ` +
          `Sq ${formatParam(next.params.Sq, next.z_unit)}`);
      })
      .catch((e: Error) => {
        if (current()) setStatus(`surface analysis: ${e.message}`);
      })
      .finally(() => {
        if (current()) setBusy(false);
      });
  };

  const exportResult = (format: "csv" | "json") => {
    if (!result) return;
    const base = `${exportBaseName(meta?.name)}_iso25178`;
    const columns = ["parameter", "value", "unit", "description"];
    const provenance = {
      analysis: "Areal surface texture (ISO 25178)",
      imageName: meta?.name,
      params: { level: result.level, region: resultRegion, roi: result.roi },
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
        <label className="k" htmlFor="afm-surface-level">Background removal</label>
        <select
          id="afm-surface-level"
          value={level}
          disabled={busy}
          onChange={(e) => setLevel(e.target.value as AfmLevel)}
        >
          <option value="none">None — already levelled</option>
          <option value="plane">Plane — recommended</option>
          <option value="quadratic">Quadratic — curved background</option>
        </select>
        <button className="fvd-btn primary" disabled={busy} onClick={run}>
          {busy ? "Analyzing…" : resultStale ? "Update analysis" : "Analyze"}
        </button>
      </div>

      {resultStale && (
        <div className="fvd-ws-note" role="status">
          Settings changed — the results below are out of date. Update the analysis before export.
        </div>
      )}

      {result && (
        <div aria-disabled={resultStale} style={resultStale ? { opacity: 0.62 } : undefined}>
          <section className="fvd-afm-summary" aria-labelledby="afm-summary-title">
            <div className="fvd-afm-section-head">
              <div>
                <h3 id="afm-summary-title">Surface summary</h3>
                <span>Key height, shape, and spatial measures</span>
              </div>
              <span className="fvd-afm-count">{result.n_pixels.toLocaleString()} px</span>
            </div>
            <div className="fvd-afm-summary-grid">
              {SUMMARY_PARAMS.map((key, index) => (
                <Metric key={key} name={key} result={result} featured primary={index === 0} />
              ))}
            </div>
          </section>

          <section aria-labelledby="afm-all-metrics-title">
            <div className="fvd-afm-section-head">
              <div>
                <h3 id="afm-all-metrics-title">All ISO 25178 parameters</h3>
                <span>Expand a family for definitions and complete values</span>
              </div>
              <span className="fvd-afm-count">{ISO_PARAMS.length} metrics</span>
            </div>
            <div className="fvd-afm-groups">
              {ISO_GROUPS.map((group) => (
                <details
                  className="fvd-afm-group"
                  key={group.title}
                  open={openGroups.includes(group.title)}
                  onToggle={(event) => {
                    const isOpen = event.currentTarget.open;
                    setOpenGroups((current) => isOpen
                      ? Array.from(new Set([...current, group.title]))
                      : current.filter((title) => title !== group.title));
                  }}
                >
                  <summary>
                    <span>{group.title}</span>
                    <span>{group.keys.length} parameters</span>
                  </summary>
                  <div className="fvd-afm-metric-list">
                    {group.keys.map((key) => (
                      <Metric key={key} name={key} result={result} />
                    ))}
                  </div>
                </details>
              ))}
            </div>
          </section>
          {!result.slopes_calibrated && (
            <div className="fvd-ws-note">
              Sdq, Sdr and slopes need heights and pixel size in length units.
            </div>
          )}
          <section className="fvd-afm-plots" aria-labelledby="afm-plots-title">
            <div className="fvd-afm-section-head">
              <div>
                <h3 id="afm-plots-title">Surface distributions</h3>
                <span>Switch views without losing your place in the results</span>
              </div>
            </div>
            <div className="fvd-afm-plot-tabs" role="tablist" aria-label="Surface plots">
              <PlotTab plot="psd" active={activePlot} onSelect={setActivePlot}>Spectrum</PlotTab>
              <PlotTab plot="height" active={activePlot} onSelect={setActivePlot}>Heights</PlotTab>
              {result.slope_hist.angle.length > 0 && (
                <PlotTab plot="slope" active={activePlot} onSelect={setActivePlot}>Slopes</PlotTab>
              )}
            </div>
            {activePlot === "psd" && (
              <CurvePlot
                id="afm-plot-psd"
                labelledBy="afm-tab-psd"
                title="Radial power spectral density"
                x={result.psd.frequency}
                y={result.psd.power}
                xLabel={`spatial frequency (1/${result.lateral_unit})`}
                yLabel={`PSD (${result.z_unit}²·${result.lateral_unit}²)`}
                log
              />
            )}
            {activePlot === "height" && (
              <CurvePlot
                id="afm-plot-height"
                labelledBy="afm-tab-height"
                title="Height distribution"
                x={result.height_hist.height}
                y={result.height_hist.percent}
                xLabel={`height (${result.z_unit})`}
                yLabel="% of pixels"
              />
            )}
            {activePlot === "slope" && result.slope_hist.angle.length > 0 && (
              <CurvePlot
                id="afm-plot-slope"
                labelledBy="afm-tab-slope"
                title="Slope distribution"
                x={result.slope_hist.angle}
                y={result.slope_hist.percent}
                xLabel="slope (°)"
                yLabel="% of pixels"
              />
            )}
          </section>
          <div className="fvd-ws-note">
            {resultRegion} · {result.level} levelling
          </div>
          <div className="fvd-ws-row">
            <button className="fvd-btn" disabled={resultStale} onClick={() => exportResult("csv")}>Export CSV</button>
            <button className="fvd-btn" disabled={resultStale} onClick={() => exportResult("json")}>Export JSON</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({
  name, result, featured = false, primary = false,
}: {
  name: IsoParam;
  result: AfmSurfaceResult;
  featured?: boolean;
  primary?: boolean;
}) {
  const value = formatParam(result.params[name], result.units[name]);
  if (featured) {
    return (
      <div className={`fvd-afm-summary-metric${primary ? " primary" : ""}`}>
        <span className="k">{SUMMARY_NAMES[name] ?? DESCRIPTIONS[name]} ({name})</span>
        <span className="v">{value}</span>
        <span className="d">
          {name === "Sq"
            ? "Root mean square of height across the analyzed area"
            : DESCRIPTIONS[name]}
        </span>
      </div>
    );
  }
  return (
    <div className="fvd-afm-metric-row">
      <span className="k">{name}</span>
      <span className="d">{DESCRIPTIONS[name]}</span>
      <span className="v">{value}</span>
    </div>
  );
}

function PlotTab({
  plot, active, onSelect, children,
}: {
  plot: SurfacePlot;
  active: SurfacePlot;
  onSelect: (plot: SurfacePlot) => void;
  children: string;
}) {
  return (
    <button
      type="button"
      id={`afm-tab-${plot}`}
      role="tab"
      aria-selected={active === plot}
      aria-controls={`afm-plot-${plot}`}
      tabIndex={active === plot ? 0 : -1}
      className="fvd-afm-plot-tab"
      onClick={() => onSelect(plot)}
      onKeyDown={(event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        const tabs = Array.from(
          event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ?? [],
        );
        const index = tabs.indexOf(event.currentTarget);
        const nextIndex = event.key === "Home" ? 0
          : event.key === "End" ? tabs.length - 1
            : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
        event.preventDefault();
        tabs[nextIndex]?.focus();
        tabs[nextIndex]?.click();
      }}
    >
      {children}
    </button>
  );
}

function CurvePlot({
  id, labelledBy, title, x, y, xLabel, yLabel, log = false,
}: {
  id: string;
  labelledBy: string;
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
    <section id={id} role="tabpanel" aria-labelledby={labelledBy}>
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
