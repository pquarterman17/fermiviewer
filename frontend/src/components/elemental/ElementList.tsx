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
//
// A row also carries a window-conflict badge (item 20) — an ADVISORY the
// shared list computes once so both EDS and EELS Maps tabs get it from one
// implementation. It never disables a row: the checkbox, colour swatch and
// remove button all keep working on a conflicted row, exactly as they do on
// any other.

import { useId, useMemo, useState } from "react";

import { setElementColor, useElementColors } from "../../lib/elemental/elementColors";
import {
  edsLineLabel,
  type Confidence,
  type RejectedElement,
} from "../../lib/elemental/identify";
import type { SpeciesRow } from "../../lib/elemental/speciesRows";
import {
  conflictsFor,
  detectWindowConflicts,
  type WindowConflict,
} from "../../lib/elemental/windowConflicts";
import { formatCountTick } from "../../lib/edsSpectrumDisplay";
import PeriodicTable from "./PeriodicTable";

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  strong: "strong",
  clear: "clear",
  weak: "weak",
  trace: "trace?",
};

/** A row's net signal, recomputed live from the current spectrum and the
 *  species' CURRENT window — as opposed to `evidence.net`, frozen at the
 *  last identify() pass. Modality-neutral: EDS's `integrateWindow` and
 *  EELS's `integrateEdge` both reduce to this shape, so a caller for either
 *  modality can fill `liveNetById` the same way. */
export interface LiveNet {
  net: number;
  sigma: number;
}

/** The row's own warning badge — absent (not just hidden) when there is
 *  nothing to say, so it never claims a table cell it does not need. */
function RowConflictBadge({ conflicts }: { conflicts: WindowConflict[] }) {
  if (conflicts.length === 0) return null;
  return (
    <span
      className="fvd-eds-conflict"
      role="img"
      aria-label="window conflict"
      title={conflicts.map((c) => c.detail).join(" ")}
    >
      ⚠
    </span>
  );
}

export default function ElementList({
  rows,
  groupCandidates = false,
  rejectedCandidates = [],
  busy,
  quantBySymbol,
  liveNetById,
  selectedId,
  onToggle,
  onSetAll,
  onReidentify,
  onAdd,
  onRemove,
  onHover,
  onFocus,
}: {
  rows: SpeciesRow[];
  /** Separate automatic recommendations, weak possibilities and manual rows. */
  groupCandidates?: boolean;
  /** Auto-ID matches that were considered but not proposed as species. */
  rejectedCandidates?: RejectedElement[];
  busy: boolean;
  /** Optional at% per symbol, shown instead of net once quantified. */
  quantBySymbol?: Record<string, number>;
  /** Live net ± σ per species id, recomputed from the current spectrum and
   *  each row's current window. Takes precedence over the stale
   *  identification-time `evidence.net` when present; a row absent from
   *  this map (no spectrum yet, or no channels in its window) falls back to
   *  `evidence.net`, then to a placeholder. Optional so a caller with
   *  nothing live to offer (e.g. today's EELS Maps tab) needs no change. */
  liveNetById?: Record<string, LiveNet | undefined>;
  /** The species id a row-click selected, for the row's highlight. Optional
   *  — a caller not tracking selection simply highlights nothing. */
  selectedId?: string | null;
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
  const candidateHeadingPrefix = useId();
  const [adding, setAdding] = useState(false);
  const shown = rows.filter((r) => r.species.visible).length;
  const recommendedRows = rows.filter(
    (row) => row.evidence?.source !== "manual" && row.evidence?.recommended,
  );
  const possibleRows = rows.filter(
    (row) => row.evidence?.source !== "manual" && row.evidence && !row.evidence.recommended,
  );
  const manualRows = rows.filter(
    (row) => !row.evidence || row.evidence.source === "manual",
  );
  const summary = groupCandidates
    ? `${recommendedRows.length} recommended · ${possibleRows.length} possible · ${rejectedCandidates.length} rejected · ${manualRows.length} selected by you · ${shown} shown`
    : `${rows.length} found · ${shown} shown`;
  const candidateSections = [
    { id: "recommended", label: "Recommended", rows: recommendedRows },
    { id: "possible", label: "Possible — review before mapping", rows: possibleRows },
    { id: "selected", label: "Selected by you", rows: manualRows },
  ].filter((section) => section.rows.length > 0);
  const conflicts = useMemo(
    () => detectWindowConflicts(rows.map((r) => r.species)),
    [rows],
  );
  const conflictedCount = useMemo(
    () => new Set(conflicts.flatMap((c) => [c.aId, c.bId])).size,
    [conflicts],
  );

  const renderRows = (sectionRows: SpeciesRow[]) => sectionRows.map((row) => {
    const { species, evidence } = row;
    const { symbol, transition, energy, visible, modality } = species;
    const color = colors(symbol);
    const atPct = quantBySymbol?.[symbol];
    const live = liveNetById?.[species.id];
    const isEels = modality === "eels";
    const transitionLabel = isEels ? transition : edsLineLabel(transition);
    const energyLabel = isEels ? `${Math.round(energy)} eV` : energy.toFixed(3);
    return (
      <li
        key={species.id}
        className={`fvd-eds-element-row${visible ? " on" : ""}${
          species.id === selectedId ? " selected" : ""
        }`}
        onMouseEnter={() => onHover(symbol)}
      >
        <input type="checkbox" checked={visible} aria-label={`Show ${symbol}`}
          onChange={(event) => onToggle(species.id, event.target.checked)} />
        <input type="color" className="fvd-eds-color-input" value={color}
          aria-label={`Colour for ${symbol}`}
          onChange={(event) => setElementColor(symbol, event.target.value)} />
        <button type="button" className="fvd-eds-element-name" style={{ color }}
          title={isEels
            ? `Frame ${symbol}-${transition} edge on the spectrum`
            : `Frame ${symbol} ${edsLineLabel(transition)} on the spectrum`}
          onClick={() => onFocus(row)}>
          {symbol}
        </button>
        <span className="k fvd-eds-element-line">{transitionLabel}</span>
        <span className="fvd-eds-element-energy">{energyLabel}</span>
        <RowConflictBadge conflicts={conflictsFor(conflicts, species.id)} />
        <span className="fvd-eds-element-net">
          {atPct != null
            ? `${atPct.toFixed(1)} at%`
            : live
              ? `${formatCountTick(live.net)} ± ${formatCountTick(live.sigma)}`
              : evidence ? formatCountTick(evidence.net) : "—"}
        </span>
        <span className="fvd-eds-strength"
          title={evidence
            ? `${evidence.significance.toFixed(0)}σ above background`
            : "not measured by the last identification"}>
          <span style={{
            width: `${Math.round((evidence?.relative ?? 0) * 100)}%`,
            background: color,
          }} />
        </span>
        <span className={`fvd-eds-conf ${evidence?.confidence ?? ""}`}>
          {evidence ? CONFIDENCE_LABEL[evidence.confidence] : "added"}
        </span>
        <button type="button" className="fvd-icon-btn"
          aria-label={`Remove ${symbol}`} onClick={() => onRemove(species.id)}>
          ✕
        </button>
      </li>
    );
  });

  return (
    <section className="fvd-eds-elements" aria-label="Identified elements">
      <header className="fvd-eds-elements-head">
        <strong>Elements</strong>
        <span className="k">
          <span className="fvd-eds-identify-summary">
            {busy ? "Identifying…" : summary}
          </span>
          {/* a conflict is always between two distinct species, so this
              count is 0 or >= 2 — never the awkward singular */}
          {conflictedCount > 0 && (
            <>
              {" · "}
              <span className="fvd-eds-conflict-count">
                {conflictedCount} windows interfere
              </span>
            </>
          )}
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
      ) : groupCandidates ? (
        <div className="fvd-eds-candidate-sections" onMouseLeave={() => onHover(null)}>
          {candidateSections.map((section) => {
            const headingId = `${candidateHeadingPrefix}-${section.id}`;
            return (
              <section key={section.id} aria-labelledby={headingId}>
                <h3
                  id={headingId}
                  className="fvd-eds-candidate-heading"
                  aria-label={`${section.label}: ${section.rows.length}`}
                >
                  <span>{section.label}</span>
                  <span>{section.rows.length}</span>
                </h3>
                <ul className="fvd-eds-element-rows">
                  {renderRows(section.rows)}
                </ul>
              </section>
            );
          })}
        </div>
      ) : (
        <ul className="fvd-eds-element-rows" onMouseLeave={() => onHover(null)}>
          {renderRows(rows)}
        </ul>
      )}

      {groupCandidates && rejectedCandidates.length > 0 && (
        <details className="fvd-eds-rejected">
          <summary>
            {rejectedCandidates.length} rejected match{rejectedCandidates.length === 1 ? "" : "es"}
          </summary>
          <ul aria-label="Rejected element matches">
            {rejectedCandidates.map((candidate, index) => (
              <li key={`${candidate.symbol}-${candidate.transition}-${index}`}>
                <strong>{candidate.symbol} {edsLineLabel(candidate.transition)}</strong>
                <span>{candidate.detail}</span>
                {candidate.net != null && (
                  <span className="k">net {formatCountTick(candidate.net)}</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
