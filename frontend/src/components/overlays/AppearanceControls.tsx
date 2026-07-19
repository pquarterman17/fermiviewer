import type { Prefs } from "../../lib/prefs";

const ACCENTS: [Prefs["accent"], string][] = [
  ["violet", "Violet"],
  ["teal", "Teal"],
  ["ocean", "Ocean"],
  ["amber", "Amber"],
  ["rose", "Rose"],
];

// Representative dark-theme hue for each swatch. The active ring stays
// neutral so a pending selection reads before its accent preview is applied.
const SWATCH: Record<Prefs["accent"], string> = {
  violet: "oklch(0.7 0.17 295)",
  teal: "oklch(0.74 0.13 185)",
  ocean: "oklch(0.68 0.15 250)",
  amber: "oklch(0.78 0.14 75)",
  rose: "oklch(0.72 0.16 12)",
};

export function AccentSwatches({
  value,
  onChange,
}: {
  value: Prefs["accent"];
  onChange: (value: Prefs["accent"]) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 6 }}>
      {ACCENTS.map(([accent, label]) => (
        <button
          key={accent}
          type="button"
          title={label}
          aria-label={label}
          aria-pressed={value === accent}
          onClick={() => onChange(accent)}
          style={{
            width: 20,
            height: 20,
            borderRadius: "50%",
            padding: 0,
            cursor: "pointer",
            background: SWATCH[accent],
            border: value === accent
              ? "2px solid var(--text)"
              : "2px solid var(--border)",
            boxShadow: value === accent
              ? "0 0 0 2px var(--surface-2) inset"
              : "none",
          }}
        />
      ))}
    </div>
  );
}
