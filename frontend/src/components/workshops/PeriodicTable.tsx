// Compact periodic-table element picker for the EDS explorer. Clicking an
// element selects it (drives the energy window / map / peak label). Elements
// present in the sample (from the acquisition header) are highlighted so the
// likely picks stand out, but any element can be chosen.

import { PERIODIC_GRID } from "../../lib/eds/periodicTable";

export default function PeriodicTable({
  selected,
  present = [],
  onSelect,
}: {
  selected: string | null;
  present?: string[];
  onSelect: (symbol: string) => void;
}) {
  const presentSet = new Set(present);
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
        const isSel = sym === selected;
        const isPresent = presentSet.has(sym);
        return (
          <button
            key={i}
            type="button"
            onClick={() => onSelect(sym)}
            aria-pressed={isSel}
            title={isPresent ? `${sym} (in sample)` : sym}
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
