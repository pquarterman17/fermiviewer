import { useEffect, useState } from "react";

import {
  analyzeInterfaceWidth,
  finiteProfilePairs,
  type InterfaceWidthResult,
} from "../../lib/api";
import {
  downloadCsv,
  downloadJson,
  exportBaseName,
  tableToCsv,
  tableToJson,
  type Cell,
} from "../../lib/resultsExport";
import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";

export interface FitRun {
  result: InterfaceWidthResult;
  sourceName: string;
  unit: string;
  x: number[];
  y: number[];
}

export function interfaceWidthRows(run: FitRun): Cell[][] {
  const { result, unit } = run;
  return [
    ["center", result.center, unit],
    ["sigma", result.sigma, unit],
    ["width_10_90", result.width_10_90, unit],
    ["amplitude", result.amplitude, "intensity"],
    ["offset", result.offset, "intensity"],
    ["r_squared", result.r_squared, ""],
    ["model", result.model, ""],
  ];
}

function fmt(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return Math.abs(value) >= 1000 || (value !== 0 && Math.abs(value) < 0.001)
    ? value.toExponential(3)
    : value.toPrecision(4);
}

export default function InterfaceWidthWorkshop() {
  const profile = useStageInfo((s) => s.profile);
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const setStatus = useViewer((s) => s.setStatus);
  const [model, setModel] = useState<InterfaceWidthResult["model"]>("erf");
  const [run, setRun] = useState<FitRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);

  useEffect(() => {
    if (run) setStale(true);
    // A profile object changes only when its measurement is recomputed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile]);

  const analyze = () => {
    if (!profile) return;
    const finite = finiteProfilePairs(profile.dist, profile.intensity);
    if (finite.x.length < 4) {
      setStatus("interface width: profile needs at least four finite samples");
      return;
    }
    setBusy(true);
    setStatus("fitting interface width…");
    analyzeInterfaceWidth(profile.dist, profile.intensity, model)
      .then((result) => {
        setRun({
          result,
          sourceName: meta?.name ?? "profile",
          unit: profile.unit,
          x: finite.x,
          y: finite.y,
        });
        setStale(false);
        setStatus(
          `interface: 10–90% ${fmt(result.width_10_90)} ${profile.unit} · R² ${result.r_squared.toFixed(3)}`,
        );
      })
      .catch((error: Error) => setStatus(`interface width: ${error.message}`))
      .finally(() => setBusy(false));
  };

  const exportResult = (format: "csv" | "json") => {
    if (!run) return;
    const provenance = {
      analysis: "Interface-width fit",
      imageName: run.sourceName,
      params: { model: run.result.model },
      profile: { x: run.x, intensity: run.y, unit: run.unit },
      fittedCurve: { x: run.result.x_fit, intensity: run.result.y_fit },
    };
    const rows = interfaceWidthRows(run);
    const base = `${exportBaseName(run.sourceName)}_interface_width`;
    if (format === "csv") {
      downloadCsv(
        `${base}.csv`,
        tableToCsv(["metric", "value", "unit"], rows, provenance),
      );
    } else {
      downloadJson(
        `${base}.json`,
        tableToJson(["metric", "value", "unit"], rows, provenance),
      );
    }
  };

  return (
    <div className="fvd-ws">
      <div className="fvd-ws-row">
        <label className="k" htmlFor="interface-model">Model</label>
        <select
          id="interface-model"
          value={model}
          disabled={busy}
          onChange={(event) => {
            setModel(event.target.value as InterfaceWidthResult["model"]);
            setStale(run !== null);
          }}
        >
          <option value="erf">Error function</option>
          <option value="sigmoid">Sigmoid</option>
        </select>
        <button
          className="fvd-btn primary"
          disabled={busy || !profile}
          onClick={analyze}
        >
          {busy ? "Fitting…" : "Fit profile"}
        </button>
      </div>

      {!profile && (
        <div className="fvd-ws-empty">
          Draw or select a line/profile measurement to populate the dock plot,
          then fit it here.
        </div>
      )}
      {profile && (
        <div className="fvd-ws-note">
          Current dock profile · {profile.intensity.length.toLocaleString()} samples ·{" "}
          {profile.unit}
        </div>
      )}
      {stale && (
        <div className="fvd-ws-note" role="status">
          Profile or model changed — rerun to update the fit.
        </div>
      )}
      {run && (
        <>
          <div className="fvd-metrics">
            <Metric label="10–90 width" value={`${fmt(run.result.width_10_90)} ${run.unit}`} />
            <Metric label="σ" value={`${fmt(run.result.sigma)} ${run.unit}`} />
            <Metric label="center" value={`${fmt(run.result.center)} ${run.unit}`} />
            <Metric label="R²" value={fmt(run.result.r_squared)} />
          </div>
          <InterfaceFitPlot run={run} />
          <div className="fvd-ws-note">
            {run.result.model} fit · amplitude {fmt(run.result.amplitude)} · offset{" "}
            {fmt(run.result.offset)} · source {run.sourceName}
          </div>
          <div className="fvd-ws-row">
            <button className="fvd-btn" onClick={() => exportResult("csv")}>
              Export CSV
            </button>
            <button className="fvd-btn" onClick={() => exportResult("json")}>
              Export JSON
            </button>
          </div>
        </>
      )}
      {!activeId && !run && (
        <div className="fvd-ws-note">Open an image before measuring a profile.</div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="fvd-metric">
      <span className="v">{value}</span>
      <span className="k">{label}</span>
    </div>
  );
}

function InterfaceFitPlot({ run }: { run: FitRun }) {
  const allX = [...run.x, ...run.result.x_fit];
  const allY = [...run.y, ...run.result.y_fit];
  const xMin = Math.min(...allX);
  const xMax = Math.max(...allX);
  const yMin = Math.min(...allY);
  const yMax = Math.max(...allY);
  const sx = (value: number) => 40 + ((value - xMin) / (xMax - xMin || 1)) * 520;
  const sy = (value: number) => 200 - ((value - yMin) / (yMax - yMin || 1)) * 170;
  const left = run.result.center - run.result.width_10_90 / 2;
  const right = run.result.center + run.result.width_10_90 / 2;
  const fitPoints = run.result.x_fit
    .map((value, index) => `${sx(value)},${sy(run.result.y_fit[index])}`)
    .join(" ");

  return (
    <section>
      <div className="fvd-ws-note">Measured profile and fitted interface</div>
      <svg
        viewBox="0 0 580 230"
        role="img"
        aria-label="Interface profile with fitted curve and 10 to 90 percent interval"
        className="fvd-ws-plot"
        style={{ width: "100%", height: 230 }}
      >
        <line x1="40" y1="200" x2="560" y2="200" stroke="var(--border)" />
        <line x1="40" y1="30" x2="40" y2="200" stroke="var(--border)" />
        {[left, run.result.center, right].map((value, index) => (
          <line
            key={value}
            x1={sx(value)}
            y1="30"
            x2={sx(value)}
            y2="200"
            stroke={index === 1 ? "var(--accent)" : "#e0a13b"}
            strokeDasharray={index === 1 ? "2 3" : "5 4"}
          />
        ))}
        <polyline
          points={fitPoints}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2.5"
        />
        {run.x.map((value, index) => (
          <circle
            key={`${value}-${index}`}
            cx={sx(value)}
            cy={sy(run.y[index])}
            r="2.5"
            fill="currentColor"
            opacity="0.55"
          />
        ))}
        <text x="300" y="222" textAnchor="middle" fontSize="11" fill="currentColor">
          distance ({run.unit})
        </text>
      </svg>
    </section>
  );
}
