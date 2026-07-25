import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  analyzeNoise,
  applyFilter,
  type NoiseResult,
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

const NO_SHAPE: number[] = [];

export function noiseRows(result: NoiseResult): Cell[][] {
  return [
    ["sigma", result.sigma, "intensity"],
    ["snr_linear", result.snr_linear, "ratio"],
    ["snr_db", result.snr_db, "dB"],
    ["noise_type", result.noise_type, ""],
    ["regression_slope", result.regression_slope, ""],
    ["regression_intercept", result.regression_intercept, ""],
    ["regression_r_squared", result.regression_r_squared, ""],
  ];
}

function fmt(value: number | null, digits = 4): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toPrecision(digits);
}

export default function NoiseWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const setStatus = useViewer((s) => s.setStatus);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const setActive = useViewer((s) => s.setActive);
  const region = useAnalysisRoi(activeId, meta?.shape ?? NO_SHAPE);
  const [method, setMethod] = useState<NoiseResult["method"]>("mad");
  const [result, setResult] = useState<NoiseResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);

  useEffect(() => {
    setResult(null);
    setStale(false);
  }, [activeId]);

  const run = () => {
    if (!activeId) return;
    setBusy(true);
    setStatus("estimating noise…");
    analyzeNoise(activeId, { method, roi: region.roi })
      .then((next) => {
        setResult(next);
        setStale(false);
        setStatus(
          `noise: σ ${fmt(next.sigma)} · SNR ${fmt(next.snr_db)} dB · ${next.noise_type}`,
        );
      })
      .catch((error: Error) => setStatus(`noise: ${error.message}`))
      .finally(() => setBusy(false));
  };

  const applyRecommendation = () => {
    if (!activeId || !result) return;
    const poisson = result.noise_type === "poisson";
    const lowSnr = result.snr_db != null && result.snr_db < 10;
    setBusy(true);
    applyFilter(
      activeId,
      poisson ? "median" : "gaussian",
      poisson ? { window_size: lowSnr ? 5 : 3 } : { sigma: lowSnr ? 2 : 1 },
    )
      .then((derived) => {
        ingestDerived([derived]);
        setActive(activeId);
        setStatus(`created ${derived.name}`);
      })
      .catch((error: Error) => setStatus(`denoise: ${error.message}`))
      .finally(() => setBusy(false));
  };

  const exportResult = (format: "csv" | "json") => {
    if (!result) return;
    const base = `${exportBaseName(meta?.name)}_noise`;
    const provenance = {
      analysis: "Noise estimate",
      imageName: meta?.name,
      params: { method: result.method, region: region.label, roi: result.roi },
      recommendation: result.recommendation,
    };
    const rows = noiseRows(result);
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

  if (!meta || (meta.kind !== "image" && meta.kind !== "spectrum_image")) {
    return <div className="fvd-ws-empty">Select a 2D image or spectrum image.</div>;
  }

  return (
    <div className="fvd-ws">
      <AnalysisRegionSelect
        choice={region.choice}
        options={region.options}
        disabled={busy}
        onChange={(choice) => {
          region.setChoice(choice);
          setStale(result !== null);
        }}
      />
      <div className="fvd-ws-row">
        <label className="k" htmlFor="noise-method">Estimator</label>
        <select
          id="noise-method"
          value={method}
          disabled={busy}
          onChange={(event) => {
            setMethod(event.target.value as NoiseResult["method"]);
            setStale(result !== null);
          }}
        >
          <option value="mad">Laplacian MAD</option>
          <option value="localvar">Local variance</option>
          <option value="both">Mean of both</option>
        </select>
        <button className="fvd-btn primary" disabled={busy} onClick={run}>
          {busy ? "Analyzing…" : "Analyze"}
        </button>
      </div>
      {stale && (
        <div className="fvd-ws-note" role="status">
          Parameters changed — rerun to update the result.
        </div>
      )}
      {result && (
        <>
          <div className="fvd-metrics">
            <Metric label="σ" value={fmt(result.sigma)} />
            <Metric label="SNR" value={`${fmt(result.snr_db)} dB`} />
            <Metric label="type" value={result.noise_type} />
            <Metric label="fit R²" value={fmt(result.regression_r_squared)} />
          </div>
          <NoiseEvidencePlot result={result} />
          <div className="fvd-ws-note">
            {result.n_pixels.toLocaleString()} pixels · {region.label} ·{" "}
            {result.method} · {result.n_blocks.toLocaleString()}{" "}
            {result.block_size}×{result.block_size} blocks
          </div>
          <div className="fvd-ws-note">
            Recommendation: {result.recommendation}
          </div>
          <div className="fvd-ws-row">
            <button className="fvd-btn" disabled={busy} onClick={applyRecommendation}>
              Apply recommended filter
            </button>
            <button className="fvd-btn" onClick={() => exportResult("csv")}>
              Export CSV
            </button>
            <button className="fvd-btn" onClick={() => exportResult("json")}>
              Export JSON
            </button>
          </div>
        </>
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

function NoiseEvidencePlot({ result }: { result: NoiseResult }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = host.current;
    if (!element || result.block_means.length < 2) return;
    const pairs = result.block_means
      .map((mean, index) => [mean, result.block_variances[index]] as const)
      .filter(([mean, variance]) => Number.isFinite(mean) && Number.isFinite(variance))
      .sort((a, b) => a[0] - b[0]);
    if (pairs.length < 2) return;
    const x = pairs.map(([mean]) => mean);
    const variance = pairs.map(([, value]) => value);
    const fit =
      result.regression_slope == null || result.regression_intercept == null
        ? variance.map(() => null)
        : x.map(
            (mean) =>
              result.regression_slope! * mean + result.regression_intercept!,
          );
    const accent =
      getComputedStyle(document.documentElement)
        .getPropertyValue("--accent")
        .trim() || "#7c5ce7";
    const plot = new uPlot(
      {
        width: element.clientWidth || 560,
        height: 220,
        scales: { x: { time: false } },
        series: [
          {},
          { label: "block variance", stroke: accent, points: { show: true, size: 5 } },
          { label: "regression", stroke: "#e0a13b", width: 2, points: { show: false } },
        ],
        axes: [
          { label: "block mean", stroke: "#888" },
          { label: "block variance", stroke: "#888" },
        ],
        legend: { show: true },
      },
      [x, variance, fit],
      element,
    );
    return () => plot.destroy();
  }, [result]);

  return (
    <section>
      <div className="fvd-ws-note">Classification evidence: variance vs mean</div>
      <div ref={host} className="fvd-ws-plot" aria-label="Noise variance versus mean plot" />
    </section>
  );
}
