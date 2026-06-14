// Scale Bar inspector card (item #33): typed length + unit dropdown
// (Å / nm / µm — user request 2026-06-09, replacing preset boxes),
// thickness, font size (default 20), position reset. Shown in the
// Image tab when the active image is calibrated (pixel_size != null).

import { useEffect, useState } from "react";

import { unitToNm } from "../../lib/geometry";
import { useViewer } from "../../store/viewer";
import Card from "./Card";

const UNITS = ["Å", "nm", "µm"] as const;
type Unit = (typeof UNITS)[number];

/** Pick the display unit that puts the value in a readable range. */
function niceUnitFor(lengthNm: number): Unit {
  if (lengthNm < 1) return "Å";
  if (lengthNm >= 1000) return "µm";
  return "nm";
}

export default function ScaleBarCard() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const sbState = useViewer((s) =>
    s.activeId ? s.scaleBars[s.activeId] : undefined,
  );
  const scaleBarVisible = useViewer((s) => s.scaleBarVisible);
  const toggleScaleBar = useViewer((s) => s.toggleScaleBar);
  const setScaleBar = useViewer((s) => s.setScaleBar);

  const current = sbState?.lengthPhys ?? null;
  const pixelUnit = meta?.pixel_unit ?? "";
  const imgFactor = unitToNm(pixelUnit); // null → not length-calibrated

  const [valStr, setValStr] = useState("");
  const [selUnit, setSelUnit] = useState<Unit>("nm");

  // Re-seed the input when the image or its stored length changes:
  // auto → empty box; custom → value converted into a readable unit.
  useEffect(() => {
    if (current == null || imgFactor == null) {
      setValStr("");
      if (imgFactor != null) {
        setSelUnit(niceUnitFor(100 * imgFactor)); // sensible default
      }
      return;
    }
    const nm = current * imgFactor;
    const u = niceUnitFor(nm);
    setSelUnit(u);
    setValStr(String(Number((nm / unitToNm(u)!).toPrecision(6))));
  }, [activeId, current, imgFactor]);

  // Only show when the active image has pixel calibration
  if (!activeId || !meta || meta.pixel_size == null) return null;

  const thickness = sbState?.thickness ?? null;
  const fontSize = sbState?.fontSize ?? null;

  const apply = (str: string, u: Unit) => {
    const v = Number(str);
    if (!Number.isFinite(v) || v <= 0 || imgFactor == null) return;
    // typed value in u → image calibration units
    setScaleBar(activeId, { lengthPhys: (v * unitToNm(u)!) / imgFactor });
  };

  const reset = () => {
    setScaleBar(activeId, {
      x: 0.02,
      y: 0.92,
      lengthPhys: null,
      thickness: null,
      fontSize: null,
    });
  };

  return (
    <Card title="Scale Bar" defaultOpen={false}>
      <div className="fvd-meta-row">
        <span className="k">Visible</span>
        <label className="fvd-toggle-label">
          <input
            type="checkbox"
            checked={scaleBarVisible}
            onChange={toggleScaleBar}
          />
        </label>
      </div>

      <div className="fvd-meta-row">
        <span className="k">Length</span>
        {imgFactor != null ? (
          <div className="fvd-sb-spin">
            <input
              type="number"
              min={0}
              step="any"
              style={{ width: 72 }}
              placeholder="auto"
              value={valStr}
              onChange={(e) => {
                setValStr(e.target.value);
                apply(e.target.value, selUnit);
              }}
            />
            <select
              value={selUnit}
              onChange={(e) => {
                const u = e.target.value as Unit;
                setSelUnit(u);
                apply(valStr, u);
              }}
            >
              {UNITS.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
            <button
              className={`fvd-seg-btn${current == null ? " active" : ""}`}
              title="Nice-number length chosen from the current zoom"
              onClick={() => {
                setValStr("");
                setScaleBar(activeId, { lengthPhys: null });
              }}
            >
              Auto
            </button>
          </div>
        ) : (
          // non-length calibrations (e.g. 1/nm diffraction): plain
          // input in the image's own units, no conversion dropdown
          <div className="fvd-sb-spin">
            <input
              type="number"
              min={0}
              step="any"
              style={{ width: 72 }}
              placeholder="auto"
              value={valStr}
              onChange={(e) => {
                setValStr(e.target.value);
                const v = Number(e.target.value);
                if (Number.isFinite(v) && v > 0) {
                  setScaleBar(activeId, { lengthPhys: v });
                }
              }}
            />
            <span className="k">{pixelUnit}</span>
            <button
              className={`fvd-seg-btn${current == null ? " active" : ""}`}
              onClick={() => {
                setValStr("");
                setScaleBar(activeId, { lengthPhys: null });
              }}
            >
              Auto
            </button>
          </div>
        )}
      </div>

      <div className="fvd-meta-row">
        <span className="k">Thickness</span>
        <div className="fvd-sb-spin">
          <button
            className="fvd-icon-btn"
            onClick={() =>
              setScaleBar(activeId, {
                thickness: Math.max(1, (thickness ?? 3) - 1),
              })
            }
          >
            −
          </button>
          <span>{thickness ?? "auto"}</span>
          <button
            className="fvd-icon-btn"
            onClick={() =>
              setScaleBar(activeId, { thickness: (thickness ?? 3) + 1 })
            }
          >
            +
          </button>
          {thickness != null && (
            <button
              className="fvd-icon-btn"
              title="Reset to auto"
              onClick={() => setScaleBar(activeId, { thickness: null })}
            >
              ↺
            </button>
          )}
        </div>
      </div>

      <div className="fvd-meta-row">
        <span className="k">Font size</span>
        <div className="fvd-sb-spin">
          <button
            className="fvd-icon-btn"
            onClick={() =>
              setScaleBar(activeId, {
                fontSize: Math.max(8, (fontSize ?? 20) - 1),
              })
            }
          >
            −
          </button>
          <span>{fontSize ?? "auto (20)"}</span>
          <button
            className="fvd-icon-btn"
            onClick={() =>
              setScaleBar(activeId, { fontSize: (fontSize ?? 20) + 1 })
            }
          >
            +
          </button>
          {fontSize != null && (
            <button
              className="fvd-icon-btn"
              title="Reset to auto"
              onClick={() => setScaleBar(activeId, { fontSize: null })}
            >
              ↺
            </button>
          )}
        </div>
      </div>

      <div className="fvd-meta-row">
        <span className="k">Position</span>
        <button className="fvd-seg-btn" onClick={reset}>
          Reset
        </button>
      </div>
    </Card>
  );
}
