// Element selector for the EDS explorer: a compact dropdown by default, with a
// toggle to the full periodic table. The choice is persisted (localStorage), so
// the picker preference sticks across sessions. Both modes call onSelect().
//
// Picking an element is also where its colour is set. The swatch writes to the
// shared element-colour registry, so choosing green for C here recolours the
// composite channel, the map tint and the spectrum's C Kα marker at once.

import { useState } from "react";

import {
  EDS_PALETTE,
  isElementColorCustom,
  resetElementColor,
  setElementColor,
  useElementColors,
} from "../../lib/elemental/elementColors";
import PeriodicTable from "./PeriodicTable";

const PICKER_KEY = "fv_eds_picker";

function ElementColorRow({ symbol }: { symbol: string }) {
  const colors = useElementColors();
  const current = colors(symbol);
  const custom = isElementColorCustom(symbol);

  return (
    <div className="fvd-eds-color-row">
      <span className="k">{symbol} colour</span>
      <input
        type="color"
        className="fvd-eds-color-input"
        value={current}
        aria-label={`Display colour for ${symbol}`}
        onChange={(event) => setElementColor(symbol, event.target.value)}
      />
      <div
        className="fvd-eds-color-presets"
        role="group"
        aria-label={`Preset colours for ${symbol}`}
      >
        {EDS_PALETTE.map((hex) => (
          <button
            key={hex}
            type="button"
            className={`fvd-eds-color-swatch${
              hex.toLowerCase() === current.toLowerCase() ? " active" : ""
            }`}
            style={{ background: hex }}
            title={hex}
            aria-label={`Set ${symbol} to ${hex}`}
            onClick={() => setElementColor(symbol, hex)}
          />
        ))}
      </div>
      <button
        type="button"
        className="fvd-btn"
        disabled={!custom}
        title={`Restore the default colour for ${symbol}`}
        onClick={() => resetElementColor(symbol)}
      >
        Default
      </button>
    </div>
  );
}

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
    localStorage.getItem(PICKER_KEY) === "periodic" ? "periodic" : "dropdown",
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
      {selected !== "(custom)" && <ElementColorRow symbol={selected} />}
    </div>
  );
}
