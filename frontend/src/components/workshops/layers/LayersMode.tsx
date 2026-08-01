// Single/Compare mode toggle, split out of LayersWorkshop.tsx
// (repo-health #33). Moved verbatim.

export function LayersMode({
  value,
  onChange,
}: {
  value: "single" | "compare";
  onChange: (value: "single" | "compare") => void;
}) {
  return (
    <div className="fvd-seg" aria-label="Layer analysis mode">
      <button
        className={`fvd-seg-btn${value === "single" ? " active" : ""}`}
        onClick={() => onChange("single")}
      >
        Single map
      </button>
      <button
        className={`fvd-seg-btn${value === "compare" ? " active" : ""}`}
        onClick={() => onChange("compare")}
      >
        Compare maps
      </button>
    </div>
  );
}
