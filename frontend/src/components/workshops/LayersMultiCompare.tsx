import { useEffect, useState } from "react";

import {
  analyzeLayersMulti,
  type ImageMeta,
  type LayersMultiResult,
} from "../../lib/api";
import {
  downloadCsv,
  downloadJson,
  tableToCsv,
  tableToJson,
  type Cell,
} from "../../lib/resultsExport";
import { useViewer } from "../../store/viewer";

const COLORS = [
  "#8b7bd8", "#38b6c4", "#e0a13a", "#3fbf87",
  "#d96a9a", "#6f9bd8", "#df7548", "#62a95c",
];

interface Props {
  activeId: string;
  mapIds: string[];
  images: Record<string, ImageMeta>;
  roi: [number, number, number, number] | null;
  regionLabel: string;
}

export function mapCompatibility(
  reference: ImageMeta,
  candidate: ImageMeta,
): string | null {
  if (reference.shape.join("×") !== candidate.shape.join("×")) {
    return `shape ${candidate.shape.join("×")} does not match ${reference.shape.join("×")}`;
  }
  const refCal = reference.pixel_size != null && reference.pixel_unit !== "";
  const candidateCal = candidate.pixel_size != null && candidate.pixel_unit !== "";
  if (refCal !== candidateCal) return "spatial calibration is missing on one map";
  if (
    refCal &&
    (reference.pixel_unit !== candidate.pixel_unit ||
      Math.abs(reference.pixel_size! - candidate.pixel_size!) >
        Math.abs(reference.pixel_size!) * 1e-6)
  ) {
    return `calibration ${candidate.pixel_size} ${candidate.pixel_unit}/px does not match`;
  }
  return null;
}

export function multiMapTable(result: LayersMultiResult): {
  columns: string[];
  rows: Cell[][];
} {
  const interfaceCount = Math.max(
    0,
    ...result.maps.map((map) => map.interfaces.length),
  );
  const layerCount = Math.max(0, ...result.maps.map((map) => map.layers.length));
  const columns = [
    "map",
    ...Array.from({ length: interfaceCount }, (_, index) => [
      `interface_${index + 1}_sigma_erf_${result.unit}`,
      `interface_${index + 1}_sigma_w_${result.unit}`,
    ]).flat(),
    ...Array.from(
      { length: layerCount },
      (_, index) => `layer_${index + 1}_thickness_${result.unit}`,
    ),
  ];
  return {
    columns,
    rows: result.maps.map((map) => [
      map.name,
      ...Array.from({ length: interfaceCount }, (_, index) => [
        map.interfaces[index]?.sigma_erf ?? null,
        map.interfaces[index]?.sigma_w ?? null,
      ]).flat(),
      ...Array.from(
        { length: layerCount },
        (_, index) => map.layers[index]?.thickness ?? null,
      ),
    ]),
  };
}

export default function LayersMultiCompare({
  activeId,
  mapIds,
  images,
  roi,
  regionLabel,
}: Props) {
  const setStatus = useViewer((s) => s.setStatus);
  const [referenceId, setReferenceId] = useState(activeId);
  const [selected, setSelected] = useState<string[]>([]);
  const [axis, setAxis] = useState<"auto" | "y" | "x">("auto");
  const [modality, setModality] =
    useState<"haadf" | "eels" | "bf" | "df">("haadf");
  const [sensitivity, setSensitivity] = useState("0.3");
  const [nLayers, setNLayers] = useState("");
  const [waviness, setWaviness] = useState(true);
  const [result, setResult] = useState<LayersMultiResult | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setReferenceId(activeId);
    setSelected([]);
    setResult(null);
  }, [activeId]);

  const reference = images[referenceId];
  const candidates = mapIds.filter((id) => id !== referenceId);
  const changeReference = (id: string) => {
    setReferenceId(id);
    setSelected((current) =>
      current.filter(
        (candidateId) =>
          candidateId !== id &&
          mapCompatibility(images[id], images[candidateId]) === null,
      ),
    );
    setResult(null);
  };

  const run = () => {
    if (!reference || selected.length === 0) return;
    const ids = [referenceId, ...selected];
    setBusy(true);
    setStatus("comparing interfaces across maps…");
    analyzeLayersMulti(ids, {
      reference: 0,
      roi,
      axis,
      sensitivity: Number(sensitivity) || 0.3,
      nLayers: Number(nLayers) || 0,
      modality,
      waviness,
    })
      .then((next) => {
        setResult(next);
        setStatus(
          `layers comparison: ${next.maps.length} maps · ${next.reference_positions.length} interfaces`,
        );
      })
      .catch((error: Error) =>
        setStatus(`layers comparison: ${error.message}`),
      )
      .finally(() => setBusy(false));
  };

  const exportResult = (format: "csv" | "json") => {
    if (!result) return;
    const table = multiMapTable(result);
    const provenance = {
      analysis: "Multi-map interface comparison",
      imageName: images[result.reference_id]?.name,
      params: {
        referenceId: result.reference_id,
        referencePositions: result.reference_positions,
        roi: result.roi,
        region: regionLabel,
        axis,
        sensitivity: Number(sensitivity) || 0.3,
        nLayers: Number(nLayers) || 0,
        modality,
        waviness,
      },
    };
    if (format === "csv") {
      downloadCsv(
        "layers_multimap_comparison.csv",
        tableToCsv(table.columns, table.rows, provenance),
      );
    } else {
      downloadJson(
        "layers_multimap_comparison.json",
        tableToJson(table.columns, table.rows, provenance),
      );
    }
  };

  return (
    <>
      <div className="fvd-ws-note">
        Detect interfaces once on a reference, then measure those exact
        positions on compatible element or score maps.
      </div>
      <div className="fvd-ws-row">
        <label className="k" htmlFor="layers-reference">Reference</label>
        <select
          id="layers-reference"
          value={referenceId}
          disabled={busy}
          onChange={(event) => changeReference(event.target.value)}
          style={{ flex: 1 }}
        >
          {mapIds.map((id) => (
            <option key={id} value={id}>{images[id].name}</option>
          ))}
        </select>
      </div>
      <div className="fvd-ws-row">
        <label className="k" htmlFor="layers-multi-axis">Axis</label>
        <select
          id="layers-multi-axis"
          value={axis}
          disabled={busy}
          onChange={(event) => setAxis(event.target.value as typeof axis)}
        >
          <option value="auto">Auto</option>
          <option value="y">Y</option>
          <option value="x">X</option>
        </select>
        <label className="k" htmlFor="layers-multi-modality">Modality</label>
        <select
          id="layers-multi-modality"
          value={modality}
          disabled={busy}
          onChange={(event) =>
            setModality(event.target.value as typeof modality)
          }
        >
          <option value="haadf">HAADF</option>
          <option value="eels">EELS/EDS</option>
          <option value="bf">BF</option>
          <option value="df">DF</option>
        </select>
      </div>
      <div className="fvd-ws-row">
        <label className="k" htmlFor="layers-multi-sensitivity">Sensitivity</label>
        <input
          id="layers-multi-sensitivity"
          value={sensitivity}
          disabled={busy}
          onChange={(event) => setSensitivity(event.target.value)}
        />
        <label className="k" htmlFor="layers-multi-count"># layers</label>
        <input
          id="layers-multi-count"
          value={nLayers}
          placeholder="auto"
          disabled={busy}
          onChange={(event) => setNLayers(event.target.value)}
        />
        <label className="k">
          <input
            type="checkbox"
            checked={waviness}
            disabled={busy}
            onChange={(event) => setWaviness(event.target.checked)}
          />
          σ_w
        </label>
      </div>
      <div className="fvd-ws-note">Comparison maps · {regionLabel}</div>
      <div style={{ maxHeight: 140, overflow: "auto" }}>
        {candidates.map((id) => {
          const reason = reference
            ? mapCompatibility(reference, images[id])
            : "no reference";
          return (
            <label
              key={id}
              className="k"
              title={reason ?? "Compatible map"}
              style={{ display: "flex", gap: 6, alignItems: "center" }}
            >
              <input
                type="checkbox"
                checked={selected.includes(id)}
                disabled={busy || reason !== null}
                onChange={() =>
                  setSelected((current) =>
                    current.includes(id)
                      ? current.filter((value) => value !== id)
                      : [...current, id],
                  )
                }
              />
              <span>{images[id].name}</span>
              {reason && <span className="dim">— {reason}</span>}
            </label>
          );
        })}
      </div>
      <div className="fvd-ws-row">
        <button
          className="fvd-btn primary"
          disabled={busy || selected.length === 0}
          onClick={run}
        >
          {busy ? "Comparing…" : `Compare ${selected.length + 1} maps`}
        </button>
      </div>

      {result && (
        <>
          <MetricChart result={result} metric="sigma_erf" title="Interface width σ_erf" />
          {waviness && (
            <MetricChart result={result} metric="sigma_w" title="Geometric waviness σ_w" />
          )}
          <ComparisonTable result={result} />
          <div className="fvd-ws-note">
            Dashed reference map: {images[result.reference_id]?.name} · interface
            positions are not independently detected on comparison maps.
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
    </>
  );
}

function MetricChart({
  result,
  metric,
  title,
}: {
  result: LayersMultiResult;
  metric: "sigma_erf" | "sigma_w";
  title: string;
}) {
  const values = result.maps.flatMap((map) =>
    map.interfaces.map((item) => item[metric]).filter((value) => value != null),
  ) as number[];
  const max = Math.max(...values, 1);
  const count = Math.max(result.reference_positions.length, 1);
  const x = (index: number) => 45 + (index / Math.max(count - 1, 1)) * 500;
  const y = (value: number) => 185 - (value / max) * 145;
  return (
    <section>
      <div className="fvd-ws-note">{title} ({result.unit})</div>
      <svg
        viewBox="0 0 570 220"
        role="img"
        aria-label={`${title} across maps and interfaces`}
        className="fvd-ws-plot"
        style={{ width: "100%", height: 220 }}
      >
        <line x1="45" y1="185" x2="545" y2="185" stroke="var(--border)" />
        {result.maps.map((map, mapIndex) => {
          const points = map.interfaces
            .map((item, index) =>
              item[metric] == null ? null : `${x(index)},${y(item[metric]!)}`,
            )
            .filter((point) => point !== null)
            .join(" ");
          return (
            <g key={map.image_id}>
              <polyline
                points={points}
                fill="none"
                stroke={COLORS[mapIndex % COLORS.length]}
                strokeWidth={map.image_id === result.reference_id ? 3 : 2}
                strokeDasharray={
                  map.image_id === result.reference_id ? "6 3" : undefined
                }
              />
              {map.interfaces.map((item, index) =>
                item[metric] == null ? null : (
                  <circle
                    key={index}
                    cx={x(index)}
                    cy={y(item[metric]!)}
                    r="3"
                    fill={COLORS[mapIndex % COLORS.length]}
                  />
                ),
              )}
            </g>
          );
        })}
        {Array.from({ length: count }, (_, index) => (
          <text
            key={index}
            x={x(index)}
            y="204"
            textAnchor="middle"
            fontSize="10"
            fill="currentColor"
          >
            I{index + 1}
          </text>
        ))}
      </svg>
      <div className="fvd-ws-row" style={{ flexWrap: "wrap" }}>
        {result.maps.map((map, index) => (
          <span className="k" key={map.image_id}>
            <span style={{ color: COLORS[index % COLORS.length] }}>●</span>{" "}
            {map.name}
          </span>
        ))}
      </div>
    </section>
  );
}

function ComparisonTable({ result }: { result: LayersMultiResult }) {
  const table = multiMapTable(result);
  return (
    <div style={{ overflow: "auto", maxHeight: 260 }}>
      <table className="fvd-ws-table">
        <thead>
          <tr>{table.columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={result.maps[rowIndex].image_id}>
              {row.map((value, index) => (
                <td key={table.columns[index]}>
                  {typeof value === "number"
                    ? Number(value.toPrecision(5))
                    : (value ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
