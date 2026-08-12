// The species list — the workspace's primary control.
//
// A cube opens, peaks are identified, and this is what the user sees: one row
// per species with its line, energy, net counts and a strength bar, showing
// unless it is only a trace. Visibility drives the maps, the overlay and the
// legend. Hovering a row highlights that element's peak on the spectrum, which
// is how "is this identification real?" gets answered without leaving the
// panel.
//
// Rows come from SPECIES (the user's decisions), with auto-ID evidence looked
// up per row and allowed to be missing — a hand-added element nothing detected
// a peak for still gets a row, it just has no net or confidence to show. See
// lib/elemental/speciesRows.ts for why the two are not one object.

import { useState } from "react";

import { setElementColor, useElementColors } from "../../lib/elemental/elementColors";
import type { Confidence } from "../../lib/elemental/identify";
import type { SpeciesRow } from "../../lib/elemental/speciesRows";
import { formatCountTick } from "../../lib/edsSpectrumDisplay";
import PeriodicTable from "./PeriodicTable";

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  strong: "strong",
  clear: "clear",
  weak: "weak",
  trace: "trace?",
};

export default function ElementList({
  rows,
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
  rows: SpeciesRow[];
  busy: boolean;
  /** Optional at% per symbol, shown instead of net once quantified. */
  quantBySymbol?: Record<string, number>;
  /** Toggle by species id, not symbol — two rows can share an element on
   *  different transitions (Fe-L2,3 and Fe-K are distinct measurements). */
  onToggle: (speciesId: string, visible: boolean) => void;
  onSetAll: (visible: boolean) => void;
  onReidentify: () => void;
  onAdd: (symbol: string) => void;
  onRemove: (speciesId: string) => void;
  /** Highlight this element's peak on the spectrum (null clears). */
  onHover: (symbol: string | null) => void;
  /** Frame this species' window on the spectrum. */
  onFocus: (row: SpeciesRow) => void;
}) {
  const colors = useElementColors();
  const [adding, setAdding] = useState(false);
  const shown = rows.filter((r) => r.species.visible).length;

  return (
    <section className="fvd-eds-elements" aria-label="Identified elements">
      <header className="fvd-eds-elements-head">
        <strong>Elements</strong>
        <span className="k">
          {busy
            ? "Identifying…"
            : `${rows.length} found · ${shown} shown`}
        </span>
        <div className="fvd-eds-elements-actions">
          <button
            type="button"
            className="fvd-btn"
            onClick={() => onSetAll(shown < rows.length)}
            disabled={rows.length === 0}
          >
            {shown < rows.length ? "All" : "None"}
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
            selected={rows.map((r) => r.species.symbol)}
            present={rows.map((r) => r.species.symbol)}
            onSelect={(symbol) => onAdd(symbol)}
          />
        </div>
      )}

      {rows.length === 0 && !busy ? (
        <div className="fvd-ws-note">
          No elements identified. Use <strong>+ Add</strong> to pick them
          manually, or <strong>Re-ID</strong> after changing the spectrum
          source.
        </div>
      ) : (
        <ul className="fvd-eds-element-rows" onMouseLeave={() => onHover(null)}>
          {rows.map((row) => {
            const { species, evidence } = row;
            const { symbol, transition, energy, visible, modality } = species;
            const color = colors(symbol);
            const atPct = quantBySymbol?.[symbol];
            // EDS lines are "Kα"/"Lα"; EELS edges have no such notation
            // (the row already carries the edge — "L23", not "L23-alpha") —
            // and the anchor is keV for EDS, eV for EELS, so the energy cell
            // needs its own unit rather than EDS's bare decimal.
            const isEels = modality === "eels";
            const transitionLabel = isEels ? transition : `${transition}α`;
            const energyLabel = isEels
              ? `${Math.round(energy)} eV`
              : energy.toFixed(3);
            return (
              <li
                key={species.id}
                className={`fvd-eds-element-row${visible ? " on" : ""}`}
                onMouseEnter={() => onHover(symbol)}
              >
                <input
                  type="checkbox"
                  checked={visible}
                  aria-label={`Show ${symbol}`}
                  onChange={(e) => onToggle(species.id, e.target.checked)}
                />
                <input
                  type="color"
                  className="fvd-eds-color-input"
                  value={color}
                  aria-label={`Colour for ${symbol}`}
                  onChange={(e) => setElementColor(symbol, e.target.value)}
                />
                <button
                  type="button"
                  className="fvd-eds-element-name"
                  style={{ color }}
                  title={
                    isEels
                      ? `Frame ${symbol}-${transition} edge on the spectrum`
                      : `Frame ${symbol} ${transition}α on the spectrum`
                  }
                  onClick={() => onFocus(row)}
                >
                  {symbol}
                </button>
                <span className="k fvd-eds-element-line">{transitionLabel}</span>
                {/* the anchor line/onset, not the window midpoint — they
                    differ once the user tunes the window */}
                <span className="fvd-eds-element-energy">{energyLabel}</span>
                <span className="fvd-eds-element-net">
                  {atPct != null
                    ? `${atPct.toFixed(1)} at%`
                    : evidence
                      ? formatCountTick(evidence.net)
                      : "—"}
                </span>
                <span
                  className="fvd-eds-strength"
                  title={
                    evidence
                      ? `${evidence.significance.toFixed(0)}σ above background`
                      : "not measured by the last identification"
                  }
                >
                  <span
                    style={{
                      width: `${Math.round((evidence?.relative ?? 0) * 100)}%`,
                      background: color,
                    }}
                  />
                </span>
                <span className={`fvd-eds-conf ${evidence?.confidence ?? ""}`}>
                  {evidence ? CONFIDENCE_LABEL[evidence.confidence] : "added"}
                </span>
                <button
                  type="button"
                  className="fvd-icon-btn"
                  aria-label={`Remove ${symbol}`}
                  onClick={() => onRemove(species.id)}
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
