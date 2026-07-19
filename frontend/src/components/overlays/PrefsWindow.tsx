// Preferences window (checklist N): a centered, sectioned settings window.
// fv_prefs is the source of truth for DEFAULTS; Save writes it and, for the
// apply-live fields, calls the matching store action so the open session
// updates at once. New-image / next-export fields are read by their
// consumers on the next open/capture/export. Replaces the old one-column
// PrefsDialog.

import { useEffect, useState, type ReactNode } from "react";

import { setCustomColormap } from "../../lib/colormaps";
import { DEFAULTS, loadPrefs, savePrefs, type Prefs } from "../../lib/prefs";
import { useViewer } from "../../store/viewer";
import { AccentSwatches } from "./AppearanceControls";
import ModalDialog from "./ModalDialog";
import { useAppearancePreview } from "./useAppearancePreview";

const SECTIONS = [
  "Appearance",
  "Tools & Layout",
  "Measurement",
  "Export",
] as const;
type Section = (typeof SECTIONS)[number];

const CMAPS = ["gray", "viridis", "inferno", "magma", "plasma", "cividis", "custom"];

// typed option tables — keep generic inference from widening to string
const THEME_OPTS: [Prefs["theme"], string][] = [
  ["dark", "Dark"],
  ["light", "Light"],
  ["system", "System"],
];
const DENSITY_OPTS: [Prefs["density"], string][] = [
  ["compact", "Compact"],
  ["regular", "Regular"],
  ["comfy", "Comfy"],
];
const TRANSFORM_OPTS: [Prefs["defaultTransform"], string][] = [
  ["linear", "Linear"],
  ["log", "Log"],
  ["equalize", "Equalize"],
];
const LAYOUT_OPTS: [Prefs["toolsLayout"], string][] = [
  ["cards", "Cards"],
  ["unified", "Unified"],
];
const SIZE_OPTS: [Prefs["overlaySize"], string][] = [
  ["XS", "XS"],
  ["S", "S"],
  ["M", "M"],
  ["L", "L"],
  ["XL", "XL"],
  ["XXL", "XXL"],
];
const LINE_WIDTH_OPTS: [number, string][] = [
  [1, "1"],
  [1.5, "1.5"],
  [2, "2"],
  [2.5, "2.5"],
  [3, "3"],
  [4, "4"],
];
const END_OPTS: [Prefs["overlayEndSymbol"], string][] = [
  ["bar", "Bar"],
  ["circle", "Circle"],
  ["square", "Square"],
  ["cross", "Cross"],
  ["none", "None"],
];
const REDUCE_OPTS: [Prefs["profileReduce"], string][] = [
  ["mean", "Mean"],
  ["sum", "Sum"],
];
const FORMAT_OPTS: [Prefs["exportFormat"], string][] = [
  ["png", "PNG"],
  ["tiff16", "TIFF-16"],
  ["jpeg", "JPEG"],
  ["svg", "SVG"],
  ["pdf", "PDF"],
];
const RES_OPTS: [number, string][] = [
  [1, "1×"],
  [2, "2×"],
  [3, "3×"],
  [4, "4×"],
];
const SIDE_OPTS: [Prefs["colorbarSide"], string][] = [
  ["left", "Left"],
  ["right", "Right"],
  ["bottom", "Bottom"],
];
const GEOM_OPTS: [Prefs["tiltGeometry"], string][] = [
  ["cross-section", "Cross-section"],
  ["surface", "Plan-view"],
];

export default function PrefsWindow() {
  const open = useViewer((s) => s.prefsOpen);
  const setOpen = useViewer((s) => s.setPrefsOpen);
  const setStatus = useViewer((s) => s.setStatus);

  const [section, setSection] = useState<Section>("Appearance");
  const [p, setP] = useState<Prefs>(loadPrefs());
  const [customCmap, setCustomCmap] = useState("");
  const appearance = useAppearancePreview(open, setOpen, setP);

  useEffect(() => {
    if (!open) return;
    setP(loadPrefs());
    setSection("Appearance");
    // surface any saved custom colormap as an editable hex list
    try {
      const stops = JSON.parse(
        localStorage.getItem("fv_custom_cmap") ?? "[]",
      ) as number[][];
      setCustomCmap(
        stops
          .map(
            ([r, g, b]) =>
              "#" +
              [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join(""),
          )
          .join(", "),
      );
    } catch {
      setCustomCmap("");
    }
  }, [open]);

  if (!open) return null;

  const set = <K extends keyof Prefs>(k: K, v: Prefs[K]) =>
    setP((prev) => ({ ...prev, [k]: v }));

  const save = () => {
    // sanitize numeric fields before persisting
    const lo = Math.min(Math.max(p.autoLoPct, 0), 49.9);
    const hi = Math.max(Math.min(p.autoHiPct, 100), lo + 0.1);
    const clean: Prefs = {
      ...p,
      autoLoPct: lo,
      autoHiPct: hi,
      inspectorGrid: Math.min(15, Math.max(3, Math.round(p.inspectorGrid))) | 1,
      profileWidth: Math.min(99, Math.max(1, Math.round(p.profileWidth))),
      scaleBarFontSize: Math.min(48, Math.max(8, Math.round(p.scaleBarFontSize))),
      exportScale: Math.min(4, Math.max(1, Math.round(p.exportScale))),
      fixedZoomW: Math.max(1, Math.round(p.fixedZoomW)),
      fixedZoomH: Math.max(1, Math.round(p.fixedZoomH)),
    };
    savePrefs(clean);

    // apply-live: push into the open session via the store actions
    const st = useViewer.getState();
    st.setTheme(clean.theme);
    st.setAccent(clean.accent);
    st.setDensity(clean.density);
    st.setToolsLayout(clean.toolsLayout);
    st.setProfileWidth(clean.profileWidth);
    st.setProfileReduce(clean.profileReduce);
    st.setColorbarSide(clean.colorbarSide);
    st.setScaleBarVisible(clean.scaleBarVisible);
    st.setOverlay({
      color: clean.overlayColor,
      size: clean.overlaySize,
      lineWidth: clean.overlayLineWidth,
      endSymbol: clean.overlayEndSymbol,
    });

    let msg = "preferences saved";
    if (customCmap.trim() && !setCustomColormap(customCmap)) {
      msg = "prefs: custom colormap needs ≥2 hex stops — not saved";
    }
    setStatus(msg);
    appearance.commit();
    setOpen(false);
  };

  const reset = () => {
    if (window.confirm("Reset all preferences to defaults?")) {
      appearance.previewAll({ ...DEFAULTS });
      setCustomCmap("");
    }
  };

  return (
    <ModalDialog
      ariaLabel="Preferences"
      className="fvd-prefs"
      onClose={appearance.cancel}
    >
        <h2>Preferences</h2>
        <div className="fvd-prefs-body">
          <nav className="fvd-prefs-nav">
            {SECTIONS.map((s) => (
              <button
                key={s}
                className={`fvd-prefs-navbtn${section === s ? " active" : ""}`}
                title={`Show ${s} settings`}
                onClick={() => setSection(s)}
              >
                {s}
              </button>
            ))}
          </nav>

          <div className="fvd-prefs-pane">
            {section === "Appearance" && (
              <>
                <div className="fvd-prefs-preview-note" role="status">
                  Previewing live · Save to keep appearance changes
                </div>
                <Row label="Theme">
                  <Seg value={p.theme} options={THEME_OPTS} onChange={(v) => appearance.preview("theme", v)} />
                </Row>
                <Row label="Color scheme" hint="accent tint; surfaces stay neutral">
                  <AccentSwatches value={p.accent} onChange={(v) => appearance.preview("accent", v)} />
                </Row>
                <Row label="Density" hint="chrome spacing & row height">
                  <Seg value={p.density} options={DENSITY_OPTS} onChange={(v) => appearance.preview("density", v)} />
                </Row>
                <Row label="Default colormap" hint="LUT for newly opened images">
                  <select value={p.defaultCmap} onChange={(e) => set("defaultCmap", e.target.value)}>
                    {CMAPS.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                </Row>
                <Row label="Custom colormap" hint="2+ comma-separated hex stops for the 'custom' colormap">
                  <input
                    type="text"
                    style={{ flex: 1, minWidth: 0 }}
                    placeholder="#000, #a070f0, #fff"
                    value={customCmap}
                    onChange={(e) => setCustomCmap(e.target.value)}
                  />
                </Row>
                <Row label="Intensity transform" hint="applied to newly opened images">
                  <Seg value={p.defaultTransform} options={TRANSFORM_OPTS} onChange={(v) => set("defaultTransform", v)} />
                </Row>
                <Row label="Invert on open">
                  <Toggle checked={p.defaultInvert} onChange={(v) => set("defaultInvert", v)} />
                </Row>
                <Row label="Auto-contrast window %" hint="low / high percentiles">
                  <Num value={p.autoLoPct} min={0} max={49.9} step={0.1} onChange={(v) => set("autoLoPct", v)} />
                  <span className="fvd-prefs-dash">–</span>
                  <Num value={p.autoHiPct} min={50} max={100} step={0.1} onChange={(v) => set("autoHiPct", v)} />
                </Row>
                <Row label="Auto-contrast on open" hint="auto-window images that carry no embedded display range">
                  <Toggle checked={p.autoContrastOnOpen} onChange={(v) => set("autoContrastOnOpen", v)} />
                </Row>
                <SubHead>Colorbar</SubHead>
                <Row label="Show colorbar by default">
                  <Toggle checked={p.colorbarOnByDefault} onChange={(v) => set("colorbarOnByDefault", v)} />
                </Row>
                <Row label="Colorbar side">
                  <Seg value={p.colorbarSide} options={SIDE_OPTS} onChange={(v) => set("colorbarSide", v)} />
                </Row>
              </>
            )}

            {section === "Tools & Layout" && (
              <>
                <Row label="Inspector tools layout" hint="separate cards vs one unified browser">
                  <Seg value={p.toolsLayout} options={LAYOUT_OPTS} onChange={(v) => set("toolsLayout", v)} />
                </Row>
                <Row label="Show minimap by default">
                  <Toggle checked={p.minimap} onChange={(v) => set("minimap", v)} />
                </Row>
                <Row label="Pixel-inspector grid" hint="odd N for the N×N value grid">
                  <Num value={p.inspectorGrid} min={3} max={15} step={2} onChange={(v) => set("inspectorGrid", v)} />
                </Row>
                <Row label="Fixed-zoom size (px)" hint="default W × H for the fixed-size zoom tool">
                  <Num value={p.fixedZoomW} min={1} max={8192} step={1} onChange={(v) => set("fixedZoomW", v)} />
                  <span className="fvd-prefs-dash">×</span>
                  <Num value={p.fixedZoomH} min={1} max={8192} step={1} onChange={(v) => set("fixedZoomH", v)} />
                </Row>
              </>
            )}

            {section === "Measurement" && (
              <>
                <Row label="Overlay color">
                  <input
                    type="color"
                    value={p.overlayColor}
                    onChange={(e) => set("overlayColor", e.target.value)}
                  />
                </Row>
                <Row label="Overlay size">
                  <Seg value={p.overlaySize} options={SIZE_OPTS} onChange={(v) => set("overlaySize", v)} />
                </Row>
                <Row label="Line width (px)" hint="measurement & annotation line thickness">
                  <Seg value={p.overlayLineWidth} options={LINE_WIDTH_OPTS} onChange={(v) => set("overlayLineWidth", v)} />
                </Row>
                <Row label="End symbol">
                  <Seg value={p.overlayEndSymbol} options={END_OPTS} onChange={(v) => set("overlayEndSymbol", v)} />
                </Row>
                <Row label="Profile width (px)" hint="default ⊥ averaging width for profile captures">
                  <Num value={p.profileWidth} min={1} max={99} step={1} onChange={(v) => set("profileWidth", v)} />
                </Row>
                <Row label="Profile reduction">
                  <Seg value={p.profileReduce} options={REDUCE_OPTS} onChange={(v) => set("profileReduce", v)} />
                </Row>
                <Row label="Show scale bar">
                  <Toggle checked={p.scaleBarVisible} onChange={(v) => set("scaleBarVisible", v)} />
                </Row>
                <Row label="Scale-bar font size (px)">
                  <Num value={p.scaleBarFontSize} min={8} max={48} step={1} onChange={(v) => set("scaleBarFontSize", v)} />
                </Row>
                <Row label="Default tilt geometry" hint="seeded onto newly opened images">
                  <Seg value={p.tiltGeometry} options={GEOM_OPTS} onChange={(v) => set("tiltGeometry", v)} />
                </Row>
              </>
            )}

            {section === "Export" && (
              <>
                <Row label="Default format">
                  <Seg value={p.exportFormat} options={FORMAT_OPTS} onChange={(v) => set("exportFormat", v)} />
                </Row>
                <Row label="Default resolution">
                  <Seg value={p.exportScale} options={RES_OPTS} onChange={(v) => set("exportScale", v)} />
                </Row>
                <Row label="Bake scale bar by default">
                  <Toggle checked={p.exportScaleBar} onChange={(v) => set("exportScaleBar", v)} />
                </Row>
                <Row label="Bake measurements by default">
                  <Toggle checked={p.exportMeasures} onChange={(v) => set("exportMeasures", v)} />
                </Row>
                <Row label="Bake colorbar by default">
                  <Toggle checked={p.exportColorbar} onChange={(v) => set("exportColorbar", v)} />
                </Row>
              </>
            )}
          </div>
        </div>

        <div className="fvd-prefs-footer">
          <button
            className="fvd-btn"
            title="Restore all preferences to defaults"
            onClick={reset}
          >
            Reset to defaults
          </button>
          <div className="fvd-prefs-footer-right">
            <button
              className="fvd-btn"
              title="Discard changes and close (Esc)"
              onClick={appearance.cancel}
            >
              Cancel
            </button>
            <button
              className="fvd-btn primary"
              title="Save and apply preferences"
              onClick={save}
            >
              Save
            </button>
          </div>
        </div>
    </ModalDialog>
  );
}

// ── small control primitives ─────────────────────────────────────────

function Row({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="fvd-prefs-row">
      <span className="k" title={hint}>
        {label}
      </span>
      <div className="fvd-prefs-ctl">{children}</div>
    </div>
  );
}

/** Light sub-group caption within a section (e.g. "Colorbar" in Appearance). */
function SubHead({ children }: { children: ReactNode }) {
  return <div className="fvd-prefs-subhead">{children}</div>;
}

function Seg<T extends string | number>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: [T, string][];
  onChange: (v: T) => void;
}) {
  return (
    <div className="fvd-seg">
      {options.map(([v, label]) => (
        <button
          key={String(v)}
          className={`fvd-seg-btn${value === v ? " active" : ""}`}
          title={`Select ${label}`}
          onClick={() => onChange(v)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="fvd-check">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
    </label>
  );
}

function Num({
  value,
  min,
  max,
  step,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <input
      type="number"
      style={{ width: 64 }}
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => {
        const v = Number(e.target.value);
        if (!Number.isNaN(v)) onChange(v);
      }}
    />
  );
}
