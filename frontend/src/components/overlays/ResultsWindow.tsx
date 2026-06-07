// Floating results table (particle/grain stats) with CSV download.
// Generic: any analysis can push {title, columns, rows} to the store.

import { useRef, useState } from "react";
import { create } from "zustand";

export interface ResultsTable {
  title: string;
  columns: string[];
  rows: (string | number | null)[][];
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

function toCsv(t: ResultsTable): string {
  const esc = (v: string | number | null) => {
    const s = v === null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [
    t.columns.map(esc).join(","),
    ...t.rows.map((r) => r.map(esc).join(",")),
  ].join("\n");
}

export default function ResultsWindow() {
  const table = useResults((s) => s.table);
  const close = useResults((s) => s.close);
  const [pos, setPos] = useState({ x: 220, y: 120 });
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);

  if (!table) return null;

  const download = () => {
    const blob = new Blob([toCsv(table)], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${table.title.replace(/\W+/g, "_").toLowerCase()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
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
          onPointerDown={(e) => e.stopPropagation()}
          onClick={download}
        >
          CSV
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
