// The element list — the workspace's primary control.
//
// A cube opens, peaks are identified, and this is what the user sees: one row
// per element with its line, window, net counts and a strength bar, each
// pre-ticked unless it is only a trace. Ticking drives the maps, the overlay
// and the legend. Hovering a row highlights that element's peak on the
// spectrum, which is how "is this identification real?" gets answered without
// leaving the panel.

import { useState } from "react";

import { setElementColor, useElementColors } from "../../lib/elemental/elementColors";
import type { Confidence, IdentifiedElement } from "../../lib/elemental/identify";
import { formatCountTick } from "../../lib/edsSpectrumDisplay";
import PeriodicTable from "./PeriodicTable";

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  strong: "strong",
  clear: "clear",
  weak: "weak",
  trace: "trace?",
};

export default function EdsElementList({
  elements,
  busy,
  quantBySymbol,
  onToggle,
  onSetAll,
  onReidentify,
  onAdd,
  onRemove,
  onHover,
  onFocus,
}: {
  elements: IdentifiedElement[];
  busy: boolean;
  /** Optional at% per symbol, shown instead of net once quantified. */
  quantBySymbol?: Record<string, number>;
  onToggle: (symbol: string, selected: boolean) => void;
  onSetAll: (selected: boolean) => void;
  onReidentify: () => void;
  onAdd: (symbol: string) => void;
  onRemove: (symbol: string) => void;
  /** Highlight this element's peak on the spectrum (null clears). */
  onHover: (symbol: string | null) => void;
  /** Frame this element's window on the spectrum. */
  onFocus: (element: IdentifiedElement) => void;
}) {
  const colors = useElementColors();
  const [adding, setAdding] = useState(false);
  const selected = elements.filter((e) => e.selected).length;

  return (
    <section className="fvd-eds-elements" aria-label="Identified elements">
      <header className="fvd-eds-elements-head">
        <strong>Elements</strong>
        <span className="k">
          {busy
            ? "Identifying…"
            : `${elements.length} found · ${selected} shown`}
        </span>
        <div className="fvd-eds-elements-actions">
          <button
            type="button"
            className="fvd-btn"
            onClick={() => onSetAll(selected < elements.length)}
            disabled={elements.length === 0}
          >
            {selected < elements.length ? "All" : "None"}
          </button>
          <button
            type="button"
            className="fvd-btn"
            onClick={onReidentify}
            disabled={busy}
            title="Re-run peak identification on the current spectrum"
          >
            Re-ID
          </button>
          <button
            type="button"
            className="fvd-btn"
            aria-pressed={adding}
            onClick={() => setAdding((on) => !on)}
            title="Add an element the identifier missed"
          >
            {adding ? "Close" : "+ Add"}
          </button>
        </div>
      </header>

      {adding && (
        <div className="fvd-eds-elements-add">
          <PeriodicTable
            selected={null}
            present={elements.map((e) => e.symbol)}
            onSelect={(symbol) => {
              onAdd(symbol);
              setAdding(false);
            }}
          />
        </div>
      )}

      {elements.length === 0 && !busy ? (
        <div className="fvd-ws-note">
          No elements identified. Use <strong>+ Add</strong> to pick them
          manually, or <strong>Re-ID</strong> after changing the spectrum
          source.
        </div>
      ) : (
        <ul className="fvd-eds-element-rows" onMouseLeave={() => onHover(null)}>
          {elements.map((element) => {
            const color = colors(element.symbol);
            const atPct = quantBySymbol?.[element.symbol];
            return (
              <li
                key={element.symbol}
                className={`fvd-eds-element-row${element.selected ? " on" : ""}`}
                onMouseEnter={() => onHover(element.symbol)}
              >
                <input
                  type="checkbox"
                  checked={element.selected}
                  aria-label={`Show ${element.symbol}`}
                  onChange={(e) => onToggle(element.symbol, e.target.checked)}
                />
                <input
                  type="color"
                  className="fvd-eds-color-input"
                  value={color}
                  aria-label={`Colour for ${element.symbol}`}
                  onChange={(e) => setElementColor(element.symbol, e.target.value)}
                />
                <button
                  type="button"
                  className="fvd-eds-element-name"
                  style={{ color }}
                  title={`Frame ${element.symbol} ${element.line}α on the spectrum`}
                  onClick={() => onFocus(element)}
                >
                  {element.symbol}
                </button>
                <span className="k fvd-eds-element-line">
                  {element.line}α
                </span>
                <span className="fvd-eds-element-energy">
                  {element.energyKev.toFixed(3)}
                </span>
                <span className="fvd-eds-element-net">
                  {atPct != null
                    ? `${atPct.toFixed(1)} at%`
                    : formatCountTick(element.net)}
                </span>
                <span
                  className="fvd-eds-strength"
                  title={`${element.significance.toFixed(0)}σ above background`}
                >
                  <span
                    style={{
                      width: `${Math.round(element.relative * 100)}%`,
                      background: color,
                    }}
                  />
                </span>
                <span className={`fvd-eds-conf ${element.confidence}`}>
                  {CONFIDENCE_LABEL[element.confidence]}
                </span>
                <button
                  type="button"
                  className="fvd-icon-btn"
                  aria-label={`Remove ${element.symbol}`}
                  onClick={() => onRemove(element.symbol)}
                >
                  ✕
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
