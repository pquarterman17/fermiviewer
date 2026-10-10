import { useEffect, useRef, useState } from "react";

import {
  analyzeForceCurve,
  DEFAULT_FORCE_SETTINGS,
  forceMaps,
  FORCE_VALUES,
  type ForceAnalysis,
  type ForceMeta,
  type ForceSettings,
  type ForceTip,
  type ForceValue,
} from "../../lib/api";
import {
  downloadCsv,
  exportBaseName,
  tableToCsv,
  type Cell,
} from "../../lib/resultsExport";
import { useAfmForce } from "../../store/afmForce";
import { useViewer } from "../../store/viewer";
import ForceCurvePlot, { type ForceAxis } from "./ForceCurvePlot";

const LABELS: Record<ForceValue, string> = {
  youngs_modulus: "Young's modulus",
  e_r: "reduced modulus",
  contact_z: "contact point (Z)",
  max_force: "maximum force",
  max_indentation: "indentation at max force",
  snap_in: "snap-in",
  adhesion: "adhesion (pull-off)",
  adhesion_energy: "work of adhesion",
  adhesion_z: "pull-off Z",
  fit_r2: "fit R²",
  fit_rms: "fit residual (rms)",
  fit_points: "points fitted",
  noise_nm: "baseline noise",
  contact_slope: "contact slope (1 on a rigid sample)",
};

const SHOWN: ForceValue[] = [
  "youngs_modulus", "max_force", "max_indentation", "adhesion", "adhesion_energy",
  "snap_in", "fit_r2", "contact_slope",
];

/** Pa → the SI prefix that keeps 1 ≤ value < 1000. */
export function formatModulus(pa: number | null): string {
  if (pa === null || !Number.isFinite(pa)) return "—";
  const units: [string, number][] = [["GPa", 1e9], ["MPa", 1e6], ["kPa", 1e3]];
  const [unit, f] = units.find(([, f]) => Math.abs(pa) >= f) ?? ["Pa", 1];
  return `${(pa / f).toPrecision(3)} ${unit}`;
}

export function formatValue(key: ForceValue, value: number | null, unit: string): string {
  if (key === "youngs_modulus") return formatModulus(value);
  if (value === null || !Number.isFinite(value)) return "—";
  const v = key === "fit_points" ? String(value) : value.toPrecision(3);
  return unit ? `${v} ${unit}` : v;
}

/** "curve 7 · row 1, col 3" for a map; "curve 7 of 12" for a list. */
export function curveLabel(meta: ForceMeta, index: number): string {
  if (meta.grid) {
    const cols = meta.grid[1];
    return `curve ${index + 1} · row ${Math.floor(index / cols) + 1}, col ${(index % cols) + 1}`;
  }
  return `curve ${index + 1} of ${meta.n_curves}`;
}

/** On a rigid sample the deflection follows Z (slope 1); a measured slope s
 *  means the InvOLS used was s times too large. */
export function calibratedInvols(used: number | null, slope: number | null): number | null {
  if (used === null || slope === null || !(slope > 0) || !Number.isFinite(slope)) return null;
  return used / slope;
}

/** A number field: empty (null) means "use the file's / no limit". */
function NumberField({
  id, label, value, placeholder, onChange, step = "any", disabled = false,
}: {
  id: string;
  label: string;
  value: number | null | undefined;
  placeholder?: string;
  onChange: (v: number | null) => void;
  step?: string;
  disabled?: boolean;
}) {
  return (
    <>
      <label className="k" htmlFor={id}>{label}</label>
      <input
        id={id}
        type="number"
        step={step}
        value={value ?? ""}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => {
          const v = e.target.value === "" ? null : Number(e.target.value);
          onChange(v !== null && Number.isFinite(v) ? v : null);
        }}
      />
    </>
  );
}

export default function AfmForceWorkshop() {
  const { files, selectedId, select, refresh, close } = useAfmForce();
  const setStatus = useViewer((s) => s.setStatus);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const meta = files.find((f) => f.id === selectedId) ?? null;
  const [index, setIndex] = useState(0);
  const [settings, setSettings] = useState<ForceSettings>(DEFAULT_FORCE_SETTINGS);
  const [axis, setAxis] = useState<ForceAxis>("z");
  const [result, setResult] = useState<ForceAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyMaps, setBusyMaps] = useState(false);
  const patch = (p: Partial<ForceSettings>) => setSettings((s) => ({ ...s, ...p }));

  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    setIndex(0);
    setSettings((s) => ({ ...s, spring_constant: null, invols: null }));
  }, [selectedId]);

  // Analyse on every change; a newer request supersedes one in flight.
  const request = useRef(0);
  useEffect(() => {
    const token = ++request.current;
    if (!meta) {
      setResult(null);
      return;
    }
    const timer = window.setTimeout(() => {
      analyzeForceCurve(meta.id, index, settings)
        .then((r) => {
          if (token !== request.current) return;
          setResult(r);
          setError(null);
        })
        .catch((e: Error) => {
          if (token !== request.current) return;
          setResult(null);
          setError(e.message);
        });
    }, 150);
    return () => window.clearTimeout(timer);
  }, [meta, index, settings]);
  useEffect(() => () => {
    request.current += 1;
  }, []);

  if (!meta) {
    return (
      <div className="fvd-ws-empty">
        Open a force-curve file (Bruker .000–.nnn force, Asylum .ibw, Nanosurf .nid) with
        File ▸ Open.
      </div>
    );
  }

  const tipIsRound = settings.tip === "sphere" || settings.tip === "flat";
  const involsLocked = meta.deflection_unit === "nm" && meta.invols === null;
  const suggested = result
    ? calibratedInvols(result.invols, result.values.contact_slope)
    : null;

  const runMaps = () => {
    setBusyMaps(true);
    setStatus("analysing every curve…");
    forceMaps(meta.id, settings)
      .then((r) => {
        if (r.images.length) ingestDerived(r.images);
        const e = r.table.youngs_modulus.filter((v): v is number => v !== null);
        const median = e.length ? [...e].sort((a, b) => a - b)[Math.floor(e.length / 2)] : null;
        setStatus(
          `${r.n - r.failed}/${r.n} curves · median E ${formatModulus(median)}` +
            (r.images.length ? ` → ${r.images.length} map images` : ""),
        );
        const rows: Cell[][] = r.table.youngs_modulus.map((_, i) => [
          i + 1, r.table.youngs_modulus[i], r.table.adhesion[i], r.table.contact_z[i],
          r.table.max_force[i], r.table.fit_r2[i],
        ]);
        if (!r.images.length) {
          downloadCsv(
            `${exportBaseName(meta.name)}_force.csv`,
            tableToCsv(
              ["curve", "youngs_modulus_Pa", "adhesion_nN", "contact_z_nm", "max_force_nN",
                "fit_r2"],
              rows,
              { analysis: "AFM force curves", imageName: meta.name, params: { ...settings } },
            ),
          );
        }
      })
      .catch((e: Error) => setStatus(`force maps: ${e.message}`))
      .finally(() => setBusyMaps(false));
  };

  return (
    <div className="fvd-ws">
      <div className="fvd-ws-row">
        <label className="k" htmlFor="force-file">File</label>
        <select id="force-file" value={meta.id} onChange={(e) => select(e.target.value)}>
          {files.map((f) => (
            <option key={f.id} value={f.id}>{f.name}</option>
          ))}
        </select>
        <button
          className="fvd-icon-btn"
          aria-label="close force file"
          title="Close this force file"
          onClick={() => void close(meta.id)}
        >
          ✕
        </button>
      </div>
      <div className="fvd-ws-note">
        {meta.parser} · {meta.n_curves} curve{meta.n_curves === 1 ? "" : "s"}
        {meta.grid ? ` (${meta.grid[0]} × ${meta.grid[1]} map)` : ""} · Z from{" "}
        {meta.z_source || "the file"}
      </div>
      {meta.n_curves > 1 && (
        <div className="fvd-ws-row">
          <button
            className="fvd-icon-btn"
            aria-label="previous curve"
            disabled={index === 0}
            onClick={() => setIndex(index - 1)}
          >
            ◀
          </button>
          <input
            aria-label="curve"
            type="range"
            min={0}
            max={meta.n_curves - 1}
            value={index}
            onChange={(e) => setIndex(Number(e.target.value))}
          />
          <button
            className="fvd-icon-btn"
            aria-label="next curve"
            disabled={index === meta.n_curves - 1}
            onClick={() => setIndex(index + 1)}
          >
            ▶
          </button>
          <span className="fvd-ws-note">{curveLabel(meta, index)}</span>
        </div>
      )}

      <div className="fvd-ws-row">
        <NumberField
          id="force-k" label="k (N/m)" value={settings.spring_constant}
          placeholder={meta.spring_constant?.toPrecision(4) ?? "required"}
          onChange={(v) => patch({ spring_constant: v })}
        />
        <NumberField
          id="force-invols" label="InvOLS (nm/V)" value={settings.invols}
          placeholder={meta.invols?.toPrecision(4) ?? (involsLocked ? "n/a" : "required")}
          disabled={involsLocked}
          onChange={(v) => patch({ invols: v })}
        />
      </div>
      <div className="fvd-ws-row">
        <label className="k" htmlFor="force-tip">Tip</label>
        <select
          id="force-tip"
          value={settings.tip}
          onChange={(e) => patch({ tip: e.target.value as ForceTip })}
        >
          <option value="sphere">Sphere (Hertz)</option>
          <option value="cone">Cone (Sneddon)</option>
          <option value="pyramid">Pyramid (Bilodeau)</option>
          <option value="flat">Flat punch</option>
        </select>
        {tipIsRound ? (
          <NumberField
            id="force-radius" label="radius (nm)" value={settings.radius_nm}
            onChange={(v) => v !== null && v > 0 && patch({ radius_nm: v })}
          />
        ) : (
          <NumberField
            id="force-angle" label="half-angle (°)" value={settings.half_angle_deg}
            onChange={(v) => v !== null && v > 0 && v < 90 && patch({ half_angle_deg: v })}
          />
        )}
        <NumberField
          id="force-poisson" label="Poisson ratio" value={settings.poisson} step="0.01"
          onChange={(v) => v !== null && v >= 0 && v <= 0.5 && patch({ poisson: v })}
        />
      </div>
      <div className="fvd-ws-row">
        <NumberField
          id="force-baseline" label="Baseline: far % of Z" value={settings.baseline_to * 100}
          onChange={(v) => v !== null && v > 0 && v <= 100 && patch({ baseline_to: v / 100 })}
        />
        <NumberField
          id="force-indent" label="fit to δ (nm)" value={settings.max_indent_nm}
          placeholder="all" onChange={(v) => patch({ max_indent_nm: v })}
        />
        <NumberField
          id="force-fmax" label="F (nN)" value={settings.max_force_nn}
          placeholder="all" onChange={(v) => patch({ max_force_nn: v })}
        />
      </div>
      <div className="fvd-ws-row">
        <label className="fvd-check">
          <input
            type="checkbox"
            checked={settings.fit}
            onChange={(e) => patch({ fit: e.target.checked })}
          />{" "}
          Fit modulus
        </label>
        <label className="k" htmlFor="force-axis">x axis</label>
        <select
          id="force-axis"
          value={axis}
          onChange={(e) => setAxis(e.target.value as ForceAxis)}
        >
          <option value="z">Z</option>
          <option value="separation">Separation</option>
        </select>
      </div>

      {error && <div className="fvd-ws-note" role="alert">{error}</div>}
      {result && (
        <>
          <ForceCurvePlot result={result} axis={axis} />
          <div className="fvd-metrics">
            {SHOWN.map((key) => (
              <div className="fvd-metric" key={key} title={LABELS[key]}>
                <span className="v">
                  {formatValue(key, result.values[key], result.units[key])}
                </span>
                <span className="k">{LABELS[key]}</span>
              </div>
            ))}
          </div>
          <div className="fvd-ws-note">
            k {result.spring_constant.toPrecision(4)} N/m
            {result.invols !== null ? ` · InvOLS ${result.invols.toPrecision(4)} nm/V` : ""}
            {suggested !== null && Math.abs(result.values.contact_slope! - 1) > 0.05 && (
              <>
                {" "}·{" "}
                <button
                  className="fvd-btn"
                  title="Only on a rigid sample: makes the contact slope 1"
                  onClick={() => patch({ invols: Number(suggested.toPrecision(4)) })}
                >
                  Use InvOLS {suggested.toPrecision(4)} nm/V
                </button>
              </>
            )}
          </div>
          <div className="fvd-ws-row">
            <button
              className="fvd-btn"
              onClick={() =>
                downloadCsv(
                  `${exportBaseName(meta.name)}_curve${index + 1}.csv`,
                  tableToCsv(
                    ["quantity", "value", "unit"],
                    FORCE_VALUES.map((k) => [LABELS[k], result.values[k], result.units[k]]),
                    { analysis: "AFM force curve", imageName: meta.name,
                      params: { curve: index + 1, ...settings } },
                  ),
                )
              }
            >
              Export CSV
            </button>
            {meta.n_curves > 1 && (
              <button className="fvd-btn primary" disabled={busyMaps} onClick={runMaps}>
                {busyMaps
                  ? "Analysing…"
                  : meta.grid
                    ? "Modulus / adhesion maps"
                    : "Analyse all → CSV"}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
