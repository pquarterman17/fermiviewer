// One editable EELS edge row (element, Z, shell, onset, signal window).
// Extracted from EelsWorkshop so the workshop keeps shrinking.

import { type EelsEdge } from "../../lib/api";

export interface EdgeRow extends EelsEdge {
  key: number;
}

export function EdgeEditor({
  row,
  onChange,
  onRemove,
}: {
  row: EdgeRow;
  onChange: (r: EdgeRow) => void;
  onRemove: () => void;
}) {
  const num = (v: string) => Number(v) || 0;
  return (
    <div className="fvd-ws-edge">
      <input
        placeholder="El"
        value={row.element}
        style={{ width: 32 }}
        onChange={(e) => onChange({ ...row, element: e.target.value })}
      />
      <input
        placeholder="Z"
        value={row.z || ""}
        style={{ width: 32 }}
        onChange={(e) => onChange({ ...row, z: num(e.target.value) })}
      />
      <select
        value={row.shell}
        onChange={(e) => onChange({ ...row, shell: e.target.value })}
      >
        {["K", "L", "M"].map((s) => (
          <option key={s}>{s}</option>
        ))}
      </select>
      <input
        placeholder="onset"
        value={row.onset_ev || ""}
        style={{ width: 52 }}
        onChange={(e) => onChange({ ...row, onset_ev: num(e.target.value) })}
      />
      <input
        placeholder="sig lo"
        value={row.signal_window[0] || ""}
        style={{ width: 52 }}
        onChange={(e) =>
          onChange({
            ...row,
            signal_window: [num(e.target.value), row.signal_window[1]],
          })
        }
      />
      <input
        placeholder="sig hi"
        value={row.signal_window[1] || ""}
        style={{ width: 52 }}
        onChange={(e) =>
          onChange({
            ...row,
            signal_window: [row.signal_window[0], num(e.target.value)],
          })
        }
      />
      <button
        className="fvd-icon-btn"
        onClick={onRemove}
        title="Remove this edge row"
      >
        ✕
      </button>
    </div>
  );
}
