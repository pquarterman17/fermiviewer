import { useState } from "react";

import {
  analyzeDefects,
  type DefectResult,
  type ImageMeta,
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

export interface DefectRun {
  result: DefectResult;
  source: ImageMeta;
  direction: number | null;
  kernelLength: number;
  gridSpacing: number;
  foilThickness: number | null;
  regionLabel: string;
}

export function defectRows(run: DefectRun): Cell[][] {
  return [
    ["intersections", run.result.intersections, "count"],
    ["test_lines", run.result.test_lines, "count"],
    ["sampled_line_length", run.result.total_line_length, run.result.pixel_unit],
    ["density", run.result.density, run.result.density_unit],
  ];
}

function fmt(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return value === 0 ? "0" : value.toPrecision(4);
}

export default function DefectWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const setActive = useViewer((s) => s.setActive);
  const setStatus = useViewer((s) => s.setStatus);
  const region = useAnalysisRoi(activeId, meta?.shape ?? NO_SHAPE);
  const [direction, setDirection] = useState("all");
  const [kernelLength, setKernelLength] = useState("15");
  const [gridSpacing, setGridSpacing] = useState("50");
  const [foilThickness, setFoilThickness] = useState("");
  const [run, setRun] = useState<DefectRun | null>(null);
  const [busy, setBusy] = useState(false);

  const analyze = () => {
    if (!activeId || !meta || meta.kind !== "image") return;
    const sourceId = activeId;
    const source = meta;
    const directionValue = direction === "all" ? null : Number(direction);
    const kernel = Math.max(1, Math.round(Number(kernelLength) || 15));
    const spacing = Math.max(1, Math.round(Number(gridSpacing) || 50));
    const foil = Number(foilThickness) > 0 ? Number(foilThickness) : null;
    setBusy(true);
    setStatus("analyzing defect lines…");
    analyzeDefects(sourceId, {
      direction: directionValue,
      kernelLength: kernel,
      gridSpacing: spacing,
      roi: region.roi,
      foilThickness: foil,
    })
      .then((result) => {
        ingestDerived([result.enhanced, result.mask]);
        setActive(sourceId);
        setRun({
          result,
          source,
          direction: directionValue,
          kernelLength: kernel,
          gridSpacing: spacing,
          foilThickness: foil,
          regionLabel: region.label,
        });
        setStatus(
          `defects: ${result.intersections} intercepts · ρ ${result.density.toExponential(2)} ${result.density_unit}`,
        );
      })
      .catch((error: Error) => setStatus(`defects: ${error.message}`))
      .finally(() => setBusy(false));
  };

  const exportResult = (format: "csv" | "json") => {
    if (!run) return;
    const provenance = {
      analysis: "Defect line density",
      imageName: run.source.name,
      params: {
        direction: run.direction ?? "sweep 0/45/90/135",
        kernelLength: run.kernelLength,
        gridSpacing: run.gridSpacing,
        foilThickness: run.foilThickness,
        region: run.regionLabel,
        roi: run.result.roi,
      },
    };
    const rows = defectRows(run);
    const base = `${exportBaseName(run.source.name)}_defects`;
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
        <label className="k" htmlFor="defect-direction">Direction</label>
        <select
          id="defect-direction"
          value={direction}
          disabled={busy}
          onChange={(event) => setDirection(event.target.value)}
        >
          <option value="all">Sweep 0°, 45°, 90°, 135°</option>
          <option value="0">0°</option>
          <option value="45">45°</option>
          <option value="90">90°</option>
          <option value="135">135°</option>
        </select>
      </div>
      <div className="fvd-ws-row">
        <label className="k" htmlFor="defect-kernel">Kernel px</label>
        <input
          id="defect-kernel"
          type="number"
          min="1"
          value={kernelLength}
          disabled={busy}
          onChange={(event) => setKernelLength(event.target.value)}
        />
        <label className="k" htmlFor="defect-grid">Grid px</label>
        <input
          id="defect-grid"
          type="number"
          min="1"
          value={gridSpacing}
          disabled={busy}
          onChange={(event) => setGridSpacing(event.target.value)}
        />
      </div>
      <div className="fvd-ws-row">
        <label className="k" htmlFor="defect-foil">
          Foil t ({meta.pixel_unit || "px"})
        </label>
        <input
          id="defect-foil"
          type="number"
          min="0"
          placeholder="optional"
          value={foilThickness}
          disabled={busy}
          onChange={(event) => setFoilThickness(event.target.value)}
        />
        <button className="fvd-btn primary" disabled={busy} onClick={analyze}>
          {busy ? "Analyzing…" : "Analyze"}
        </button>
      </div>

      {run && (
        <>
          <div className="fvd-metrics">
            <Metric label="intercepts" value={run.result.intersections.toLocaleString()} />
            <Metric label="test lines" value={run.result.test_lines.toLocaleString()} />
            <Metric label="density" value={fmt(run.result.density)} />
            <Metric label="unit" value={run.result.density_unit} />
          </div>
          <DefectGridPreview run={run} />
          <div className="fvd-ws-note">
            Sampled line length {fmt(run.result.total_line_length)}{" "}
            {run.result.pixel_unit} · {run.regionLabel}
          </div>
          <div className="fvd-ws-note">
            Intercepts are counted where the thresholded response crosses the
            test grid. The analysis does not localize individual defects.
          </div>
          <div className="fvd-ws-row">
            <button className="fvd-btn" onClick={() => setActive(run.result.enhanced.id)}>
              Inspect response
            </button>
            <button className="fvd-btn" onClick={() => setActive(run.result.mask.id)}>
              Inspect mask
            </button>
            <button className="fvd-btn" onClick={() => setActive(run.source.id)}>
              Source
            </button>
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="fvd-metric">
      <span className="v">{value}</span>
      <span className="k">{label}</span>
    </div>
  );
}

function DefectGridPreview({ run }: { run: DefectRun }) {
  const [height, width] = run.source.shape;
  const roi = run.result.roi ?? [1, 1, height, width];
  const [r1, c1, r2, c2] = roi;
  return (
    <section>
      <div className="fvd-ws-note">Sampling grid on source region</div>
      <div style={{ position: "relative", aspectRatio: `${width} / ${height}` }}>
        <img
          src={`/api/image/${run.source.id}/render`}
          alt=""
          style={{ width: "100%", height: "100%", objectFit: "fill" }}
        />
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Defect test-line grid over the analysis region"
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
        >
          <rect
            x={c1 - 1}
            y={r1 - 1}
            width={c2 - c1 + 1}
            height={r2 - r1 + 1}
            fill="none"
            stroke="#f3c04f"
            strokeWidth="1.5"
          />
          {run.result.h_rows.map((row) => (
            <line
              key={`h-${row}`}
              x1={c1 - 1}
              x2={c2}
              y1={r1 - 1 + row}
              y2={r1 - 1 + row}
              stroke="#45d6c7"
              strokeWidth="1"
            />
          ))}
          {run.result.v_cols.map((col) => (
            <line
              key={`v-${col}`}
              x1={c1 - 1 + col}
              x2={c1 - 1 + col}
              y1={r1 - 1}
              y2={r2}
              stroke="#45d6c7"
              strokeWidth="1"
            />
          ))}
        </svg>
      </div>
    </section>
  );
}
