// Shared presentational parameter-field row used by BOTH the modal
// ParamDialog (menu commands) and the inline TransformPanel expanders.
// One renderer keeps the two param surfaces visually and behaviourally
// identical (number fields coerce on blur the same way in both).

import type { ParamField } from "../../lib/params";

export function ParamFieldRow({
  field,
  value,
  onChange,
  autoFocus = false,
}: {
  field: ParamField;
  value: number | string | boolean | undefined;
  onChange: (v: number | string | boolean) => void;
  autoFocus?: boolean;
}) {
  const f = field;
  return (
    <div className="fvd-ws-row">
      <span className="k" title={f.hint}>
        {f.label}
      </span>
      {f.type === "number" && (
        <input
          autoFocus={autoFocus}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          onBlur={(e) => {
            const n = Number(e.target.value);
            onChange(Number.isFinite(n) ? n : (f.default as number));
          }}
        />
      )}
      {f.type === "text" && (
        <input
          autoFocus={autoFocus}
          style={{ flex: 1 }}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {f.type === "select" && (
        <select
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
        >
          {(f.options ?? []).map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      )}
      {f.type === "boolean" && (
        <label className="fvd-check">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
          />
        </label>
      )}
    </div>
  );
}
