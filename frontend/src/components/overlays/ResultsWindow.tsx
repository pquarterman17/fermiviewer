// Floating results table (particle/grain stats) with CSV download.
// Generic: any analysis can push {title, columns, rows} to the store.

import { useRef, useState } from "react";
import { create } from "zustand";

import {
  downloadCsv,
  downloadJson,
  exportBaseName,
  tableToCsv,
  tableToJson,
  type ResultMeta,
} from "../../lib/resultsExport";

export interface ResultsTable {
  title: string;
  columns: string[];
  rows: (string | number | null)[][];
  /** optional provenance (image name, analysis params) for the export */
  meta?: ResultMeta;
}

interface ResultsState {
  table: ResultsTable | null;
  show: (t: ResultsTable) => void;
  close: () => void;
}

export const useResults = create<ResultsState>((set) => ({
  table: null,
  show: (table) => set({ table }),
  close: () => set({ table: null }),
}));

export default function ResultsWindow() {
  const table = useResults((s) => s.table);
  const close = useResults((s) => s.close);
  const [pos, setPos] = useState({ x: 220, y: 120 });
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);

  if (!table) return null;

  const download = (format: "csv" | "json") => {
    const meta: ResultMeta = { analysis: table.title, ...table.meta };
    const slug = table.title.replace(/\W+/g, "_").toLowerCase();
    const base = `${exportBaseName(table.meta?.imageName)}_${slug}`;
    if (format === "json") {
      downloadJson(`${base}.json`, tableToJson(table.columns, table.rows, meta));
    } else {
      downloadCsv(`${base}.csv`, tableToCsv(table.columns, table.rows, meta));
    }
  };

  return (
    <div
      className="fvd-glass fvd-tool-window fvd-results"
      style={{ left: pos.x, top: pos.y, zIndex: 400 }}
    >
      <div
        className="fvd-tool-title"
        onPointerDown={(e) => {
          dragRef.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y };
          (e.target as Element).setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (dragRef.current) {
            setPos({
              x: Math.max(0, e.clientX - dragRef.current.dx),
              y: Math.max(0, e.clientY - dragRef.current.dy),
            });
          }
        }}
        onPointerUp={(e) => {
          dragRef.current = null;
          (e.target as Element).releasePointerCapture(e.pointerId);
        }}
      >
        <button
          className="fvd-tool-close"
          title="Close"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={close}
        />
        <span>{table.title}</span>
        <span style={{ flex: 1 }} />
        <button
          className="fvd-btn fvd-inline-toggle"
          title="Download as CSV"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => download("csv")}
        >
          CSV
        </button>
        <button
          className="fvd-btn fvd-inline-toggle"
          title="Download as JSON (with provenance)"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => download("json")}
        >
          JSON
        </button>
      </div>
      <div className="fvd-tool-body fvd-results-body">
        <table className="fvd-ws-table">
          <thead>
            <tr>
              {table.columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((r, i) => (
              <tr key={i}>
                {r.map((v, j) => (
                  <td key={j}>
                    {typeof v === "number"
                      ? Number(v.toPrecision(5))
                      : (v ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
