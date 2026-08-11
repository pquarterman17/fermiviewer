// Compact periodic-table element picker for the EDS explorer. Clicking an
// element selects it (drives the energy window / map / peak label). Elements
// present in the sample (from the acquisition header) are highlighted so the
// likely picks stand out, but any element can be chosen.
//
// `selected` takes either ONE symbol (the Explore flow, which tunes a single
// window) or a LIST of them (the species list, which builds a set). One prop
// rather than a second multi-select flag: the two modes differ only in how
// many symbols are lit, and a component with both props could be handed
// contradictory ones. Click semantics stay the caller's business — the picker
// reports the symbol and the caller decides whether that means select or
// toggle.

import { PERIODIC_GRID } from "../../lib/elemental/periodicTable";

export default function PeriodicTable({
  selected,
  present = [],
  onSelect,
}: {
  selected: string | readonly string[] | null;
  present?: string[];
  onSelect: (symbol: string) => void;
}) {
  const presentSet = new Set(present);
  const selectedSet = new Set(
    selected == null ? [] : typeof selected === "string" ? [selected] : selected,
  );
  const multi = typeof selected !== "string" && selected != null;
  return (
    <div
      role="grid"
      aria-label="Periodic table element picker"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(18, 1fr)",
        gap: 2,
      }}
    >
      {PERIODIC_GRID.flat().map((sym, i) => {
        if (!sym) return <span key={i} aria-hidden="true" />;
        const isSel = selectedSet.has(sym);
        const isPresent = presentSet.has(sym);
        const title = [
          sym,
          isPresent ? "(in sample)" : "",
          multi ? (isSel ? "— click to remove" : "— click to add") : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          <button
            key={i}
            type="button"
            onClick={() => onSelect(sym)}
            aria-pressed={isSel}
            title={title}
            style={{
              padding: "3px 0",
              fontSize: 10,
              lineHeight: 1.1,
              border: "1px solid rgba(128,128,128,0.35)",
              borderRadius: 2,
              cursor: "pointer",
              fontWeight: isPresent ? 700 : 400,
              color: isSel ? "#fff" : "inherit",
              background: isSel
                ? "#2563eb"
                : isPresent
                  ? "rgba(37,99,235,0.20)"
                  : "transparent",
            }}
          >
            {sym}
          </button>
        );
      })}
    </div>
  );
}
