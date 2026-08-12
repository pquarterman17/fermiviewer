// Quantify / Model-fit tab body (E0/beta controls, edge table, quantify +
// model-fit + ELNES buttons, and their result panels), split out of
// EelsWorkshop.tsx (repo-health #33). Moved verbatim; state stays owned by
// the parent and is threaded through as explicit props.

import type { Dispatch, SetStateAction } from "react";

import {
  type EelsFitResult,
  type EelsQuantResult,
  type ElnesResult,
  type ImageMeta,
} from "../../../lib/api";
import {
  csvBaseName,
  downloadCsv,
  eelsQuantToCsv,
} from "../../../lib/eelsQuantCsv";
import { EdgeEditor, type EdgeRow } from "../EelsEdgeEditor";
import { EelsFitResults, EelsQuantResults } from "../EelsResults";
import { useEelsQuantMapJob } from "../useEelsQuantMapJob";
import type { EelsTab } from "./eelsEdges";

export default function EelsQuantifyPanel({
  tab,
  isCube,
  e0Kv,
  setE0Kv,
  betaMrad,
  setBetaMrad,
  quantMethod,
  setQuantMethod,
  addEdge,
  edges,
  setEdges,
  runQuantify,
  quantMapJob,
  runModelFit,
  runModelFitMaps,
  runElnes,
  fitResult,
  elnes,
  quant,
  meta,
  activeId,
  setStatus,
}: {
  tab: EelsTab;
  isCube: boolean;
  e0Kv: number;
  setE0Kv: (v: number) => void;
  betaMrad: number;
  setBetaMrad: (v: number) => void;
  quantMethod: string;
  setQuantMethod: (v: string) => void;
  addEdge: () => void;
  edges: EdgeRow[];
  setEdges: Dispatch<SetStateAction<EdgeRow[]>>;
  runQuantify: () => void;
  quantMapJob: ReturnType<typeof useEelsQuantMapJob>;
  runModelFit: () => void;
  runModelFitMaps: () => void;
  runElnes: () => void;
  fitResult: EelsFitResult | null;
  elnes: ElnesResult | null;
  quant: EelsQuantResult | null;
  meta: ImageMeta | null;
  activeId: string | null;
  setStatus: (msg: string) => void;
}) {
  return (
    <>
      <div className="fvd-ws-row">
        <span className="k">E₀ kV</span>
        <input
          type="number"
          value={e0Kv}
          min={60}
          max={1000}
          step={10}
          style={{ width: 52 }}
          onChange={(e) => setE0Kv(Number(e.target.value) || 200)}
        />
        <span className="k">β mrad</span>
        <input
          type="number"
          value={betaMrad}
          min={1}
          max={100}
          step={1}
          style={{ width: 44 }}
          onChange={(e) => setBetaMrad(Number(e.target.value) || 10)}
        />
        <select
          value={quantMethod}
          onChange={(e) => setQuantMethod(e.target.value)}
        >
          <option value="powerlaw">power-law</option>
          <option value="exponential">exponential</option>
        </select>
      </div>
      <div className="fvd-ws-section">
        <span>Edges</span>
        <button
          className="fvd-btn"
          onClick={addEdge}
          title="Add an edge row to quantify"
        >
          + edge
        </button>
        {tab === "Quantify" ? (
          <>
            <button
              className="fvd-btn"
              onClick={runQuantify}
              disabled={edges.length === 0}
              title="Quantify at% from the edge windows"
            >
              Quantify
            </button>
            <button
              className="fvd-btn"
              title="Per-pixel at% composition maps (SI cubes)"
              onClick={quantMapJob.run}
              disabled={edges.length === 0 || !isCube || quantMapJob.busy}
            >
              {quantMapJob.busy ? "Mapping…" : "Maps"}
            </button>
            {quantMapJob.progress && (
              <span className="fvd-ws-note" role="status">
                {quantMapJob.progress}
              </span>
            )}
          </>
        ) : (
          <>
            <button
              className="fvd-btn"
              title="Fit background and all edges simultaneously"
              onClick={runModelFit}
              disabled={edges.length === 0}
            >
              Fit spectrum
            </button>
            <button
              className="fvd-btn"
              title="Per-pixel model-fit at% maps (SI cubes)"
              onClick={runModelFitMaps}
              disabled={edges.length === 0 || !isCube}
            >
              Fit maps
            </button>
            <button
              className="fvd-btn"
              title="ELNES fine-structure extraction"
              onClick={runElnes}
              disabled={edges.length === 0}
            >
              ELNES
            </button>
          </>
        )}
      </div>
      {tab === "Model fit" && fitResult && (
        <EelsFitResults result={fitResult} imageName={meta?.name} />
      )}
      {tab === "Model fit" && elnes && (
        <div className="fvd-ws-note">
          ELNES · edge jump {elnes.edge_jump.toExponential(2)} · onset{" "}
          {elnes.edge_onset.toFixed(1)} eV · {elnes.relative_energy.length} pts
        </div>
      )}
      {edges.map((row, i) => (
        <EdgeEditor
          key={row.key}
          row={row}
          onChange={(r) =>
            setEdges((rows) => rows.map((x, j) => (j === i ? r : x)))
          }
          onRemove={() => setEdges((rows) => rows.filter((_, j) => j !== i))}
        />
      ))}
      {tab === "Quantify" && quant && (
        <EelsQuantResults
          result={quant}
          onExport={() => {
            const base = csvBaseName(meta?.name);
            downloadCsv(
              `${base}_eels_quant.csv`,
              eelsQuantToCsv(quant, {
                imageName: meta?.name ?? activeId ?? "",
              }),
            );
            setStatus(`EELS: exported ${quant.elements.length} elements`);
          }}
        />
      )}
    </>
  );
}
