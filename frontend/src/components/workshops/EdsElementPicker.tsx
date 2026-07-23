// Element selector for the EDS explorer: a periodic table by default, with a
// toggle to the compact dropdown. The choice is persisted (localStorage), so
// the picker preference sticks across sessions. Both modes call onSelect().

import { useState } from "react";

import PeriodicTable from "./PeriodicTable";

const PICKER_KEY = "fv_eds_picker";

export default function EdsElementPicker({
  selected,
  elements,
  onSelect,
}: {
  selected: string; // "(custom)" or an element symbol
  elements: string[]; // elements present in the sample (acquisition header)
  onSelect: (symbol: string) => void;
}) {
  const [mode, setMode] = useState<"periodic" | "dropdown">(() =>
    localStorage.getItem(PICKER_KEY) === "dropdown" ? "dropdown" : "periodic",
  );
  const toggle = () => {
    const next = mode === "periodic" ? "dropdown" : "periodic";
    setMode(next);
    localStorage.setItem(PICKER_KEY, next);
  };
  const ddItems = ["(custom)", ...elements];

  return (
    <div style={{ flex: 1 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          marginBottom: 4,
        }}
      >
        <button
          type="button"
          className="fvd-btn"
          style={{ fontSize: 11, padding: "1px 6px" }}
          onClick={toggle}
          title="Switch between the periodic table and the dropdown list"
        >
          {mode === "periodic" ? "▾ List" : "⊞ Table"}
        </button>
      </div>
      {mode === "periodic" ? (
        <PeriodicTable
          selected={selected === "(custom)" ? null : selected}
          present={elements}
          onSelect={onSelect}
        />
      ) : (
        <select
          value={selected}
          style={{ width: "100%" }}
          onChange={(e) => onSelect(e.target.value)}
        >
          {ddItems.map((el) => (
            <option key={el} value={el}>
              {el}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
