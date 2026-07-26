import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  analyzeRoughness,
  type RoughnessResult,
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
const METRICS = ["Ra", "Rq", "Rz", "Rp", "Rv", "Rsk", "Rku", "SAR"] as const;

export function roughnessRows(result: RoughnessResult): Cell[][] {
  return METRICS.map((key) => [
    key,
    result[key],
    key === "SAR" || key === "Rsk" || key === "Rku" ? "" : result.unit,
  ]);
}

export default function RoughnessWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const setStatus = useViewer((s) => s.setStatus);
  const region = useAnalysisRoi(activeId, meta?.shape ?? NO_SHAPE);
  const [level, setLevel] = useState<RoughnessResult["level"]>("plane");
  const [result, setResult] = useState<RoughnessResult | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setResult(null);
  }, [activeId]);

  const run = () => {
    if (!activeId) return;
    setBusy(true);
    setStatus("surface roughness…");
    analyzeRoughness(activeId, { level, roi: region.roi })
      .then((next) => {
        setResult(next);
        setStatus(
          `roughness: Ra ${next.Ra.toPrecision(4)} · Rq ${next.Rq.toPrecision(4)} ${next.unit}`,
        );
      })
      .catch((error: Error) =>
        setStatus(`surface roughness: ${error.message}`),
      )
      .finally(() => setBusy(false));
  };

  const exportResult = (format: "csv" | "json") => {
    if (!result) return;
    const base = `${exportBaseName(meta?.name)}_roughness`;
    const provenance = {
      analysis: "Surface roughness",
      imageName: meta?.name,
      params: { level: result.level, region: region.label, roi: result.roi },
    };
    if (format === "csv") {
      downloadCsv(
        `${base}.csv`,
        tableToCsv(["metric", "value", "unit"], roughnessRows(result), provenance),
      );
    } else {
      downloadJson(
        `${base}.json`,
        tableToJson(
          ["metric", "value", "unit"],
          roughnessRows(result),
          provenance,
        ),
      );
    }
  };

  if (!meta || meta.kind !== "image") {
    return <div className="fvd-ws-empty">Select a 2D image.</div>;
  }

  return (
    <div className="fvd-ws">
      <AnalysisRegionSelect
        choice={region.choice}
        options={region.options}
        disabled={busy}
        onChange={region.setChoice}
      />
      <div className="fvd-ws-row">
        <label className="k" htmlFor="roughness-level">Level</label>
        <select
          id="roughness-level"
          value={level}
          disabled={busy}
          onChange={(event) =>
            setLevel(event.target.value as RoughnessResult["level"])
          }
        >
          <option value="none">None</option>
          <option value="plane">Plane</option>
          <option value="quadratic">Quadratic</option>
        </select>
        <button
          className="fvd-btn primary"
          disabled={busy}
          onClick={run}
        >
          {busy ? "Analyzing…" : "Analyze"}
        </button>
      </div>

      {result && (
        <>
          <RoughnessMetrics result={result} />
          <BearingPlot
            result={result}
            onExportCsv={() => exportResult("csv")}
          />
          <div className="fvd-ws-note">
            {result.n_pixels.toLocaleString()} valid pixels · {region.label} ·{" "}
            {result.level} leveling
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
    </div>
  );
}

function RoughnessMetrics({ result }: { result: RoughnessResult }) {
  return (
    <div className="fvd-metrics">
      {METRICS.map((key) => (
        <div className="fvd-metric" key={key}>
          <span className="v">{formatMetric(key, result[key], result.unit)}</span>
          <span className="k">{key}</span>
        </div>
      ))}
    </div>
  );
}

function formatMetric(
  key: (typeof METRICS)[number],
  value: number,
  unit: string,
): string {
  if (!Number.isFinite(value)) return "—";
  const rendered = Math.abs(value) >= 1000 || (value !== 0 && Math.abs(value) < 0.001)
    ? value.toExponential(3)
    : value.toPrecision(4);
  return key === "SAR" || key === "Rsk" || key === "Rku"
    ? rendered
    : `${rendered} ${unit}`;
}

function BearingPlot({
  result,
  onExportCsv,
}: {
  result: RoughnessResult;
  onExportCsv: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => {
    const element = host.current;
    if (!element || result.bearing_fraction.length < 2) return;
    const accent =
      getComputedStyle(document.documentElement)
        .getPropertyValue("--accent")
        .trim() || "#7c5ce7";
    plotRef.current = new uPlot(
      {
        width: element.clientWidth || 560,
        height: 190,
        scales: { x: { time: false } },
        series: [{}, { label: "height", stroke: accent, width: 1.5 }],
        axes: [
          { label: "material ratio (%)", stroke: "#888" },
          { label: result.unit, stroke: "#888" },
        ],
        legend: { show: false },
        cursor: { y: false },
      },
      [
        result.bearing_fraction.map((fraction) => fraction * 100),
        result.bearing_heights,
      ],
      element,
    );
    return () => {
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [result]);

  return (
    <section>
      <div className="fvd-ws-note">Material ratio / bearing curve</div>
      <PlotContextSurface
        ref={host}
        plotRef={plotRef}
        label="Material ratio bearing curve"
        filename="material-ratio-bearing-curve.png"
        className="fvd-ws-plot"
        onExportData={onExportCsv}
        exportLabel="Export roughness CSV"
      />
    </section>
  );
}
