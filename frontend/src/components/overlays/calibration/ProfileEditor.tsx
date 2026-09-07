import { useState } from "react";

import type {
  CalibrationProfile,
  ProfileDraft,
  ProfileKind,
  ProfileQuantity,
} from "../../../lib/api";
import { KIND_LABEL, PROFILE_KINDS, TEXT_FIELDS, withQuantity } from "./profileDraft";

type RangeKey = "beam_energy_kev" | "magnification" | "camera_length_mm";

const RANGE_LABELS: Record<RangeKey, [string, string]> = {
  beam_energy_kev: ["Beam energy", "keV"],
  magnification: ["Magnification", "×"],
  camera_length_mm: ["Camera length", "mm"],
};
const PIXEL_FIELDS = ["pixel_size_row", "pixel_size_column"] as const;
const LENGTH_UNITS = ["pm", "Å", "nm", "µm", "mm"];

interface PixelPairDraft {
  row: string;
  column: string;
  unit: string;
  rowSigma: string;
  columnSigma: string;
}

interface Props {
  profile: CalibrationProfile | null;
  draft: ProfileDraft;
  knownFields: Record<ProfileKind, Record<string, string>>;
  creating: boolean;
  busy: boolean;
  onChange: (draft: ProfileDraft) => void;
  onSave: () => void;
  onCancel: () => void;
}

export default function ProfileEditor({
  profile,
  draft,
  knownFields,
  creating,
  busy,
  onChange,
  onSave,
  onCancel,
}: Props) {
  const [ranges, setRanges] = useState<Record<RangeKey, [string, string]>>(() =>
    Object.fromEntries(
      (Object.keys(RANGE_LABELS) as RangeKey[]).map((key) => [
        key,
        draft.validity[key]?.map(String) ?? ["", ""],
      ]),
    ) as Record<RangeKey, [string, string]>,
  );
  const [pixelPair, setPixelPair] = useState<PixelPairDraft>(() => {
    const row = draft.fields.pixel_size_row;
    const column = draft.fields.pixel_size_column;
    return {
      row: row == null ? "" : String(row.value),
      column: column == null ? "" : String(column.value),
      unit: row?.unit ?? column?.unit ?? "nm",
      rowSigma: row?.sigma == null ? "" : String(row.sigma),
      columnSigma: column?.sigma == null ? "" : String(column.sigma),
    };
  });
  const fieldNames = Array.from(
    new Set([...Object.keys(knownFields[draft.kind] ?? {}), ...Object.keys(draft.fields)]),
  );
  const textNames = Array.from(
    new Set([...TEXT_FIELDS[draft.kind], ...Object.keys(draft.text)]),
  );

  const setRange = (key: RangeKey, index: 0 | 1, raw: string) => {
    const next: [string, string] = [...ranges[key]];
    next[index] = raw;
    setRanges({ ...ranges, [key]: next });
    onChange({
      ...draft,
      validity: {
        ...draft.validity,
        [key]: next.every((value) => value !== "")
          ? [Number(next[0]), Number(next[1])]
          : null,
      },
    });
  };

  const updatePixelPair = (next: PixelPairDraft) => {
    setPixelPair(next);
    const fields = { ...draft.fields };
    delete fields.pixel_size_row;
    delete fields.pixel_size_column;
    if (next.row !== "" && next.column !== "") {
      const quantity = (value: string, sigma: string): ProfileQuantity => ({
        value: Number(value),
        unit: next.unit,
        ...(sigma === "" ? {} : { sigma: Number(sigma) }),
      });
      fields.pixel_size_row = quantity(next.row, next.rowSigma);
      fields.pixel_size_column = quantity(next.column, next.columnSigma);
    }
    onChange({ ...draft, fields });
  };

  return (
    <div className="fvd-cal-center-editor">
      <header className="fvd-cal-center-detail-head">
        <div>
          <span className="fvd-cal-center-eyebrow">
            {creating ? "New profile" : `${draft.kind} · version ${profile?.version ?? 1}`}
          </span>
          <h3>{creating ? "Create calibration profile" : draft.name}</h3>
        </div>
        <div className="fvd-btn-row">
          <button className="fvd-btn" disabled={busy} onClick={onCancel}>Cancel</button>
          <button
            className="fvd-btn primary"
            disabled={busy || draft.name.trim() === ""}
            onClick={onSave}
          >
            {busy ? "Saving…" : creating ? "Create profile" : "Save new version"}
          </button>
        </div>
      </header>

      <div className="fvd-cal-center-form-scroll">
        <section className="fvd-cal-form-section">
          <h4>Identity</h4>
          <div className="fvd-cal-form-grid">
            <label className="wide">Name<input autoFocus value={draft.name} onChange={(e) => onChange({ ...draft, name: e.target.value })} /></label>
            <label>Type<select disabled={!creating} value={draft.kind} onChange={(e) => onChange({ ...draft, kind: e.target.value as ProfileKind, fields: {}, text: {} })}>{PROFILE_KINDS.map((kind) => <option key={kind} value={kind}>{KIND_LABEL[kind].slice(0, -1)}</option>)}</select></label>
            {textNames.map((name) => (
              <label key={name}>{name.replaceAll("_", " ")}<input value={draft.text[name] ?? ""} readOnly={name === "legacy_key"} title={name === "legacy_key" ? "Preserved import identity" : undefined} onChange={(e) => name !== "legacy_key" && onChange({ ...draft, text: { ...draft.text, [name]: e.target.value } })} /></label>
            ))}
          </div>
        </section>

        <section className="fvd-cal-form-section">
          <div className="fvd-cal-form-title"><h4>Calibration values</h4><span>Leave unused values blank</span></div>
          {draft.kind === "acquisition" && (
            <p className="fvd-cal-pair-note">Spatial pixel size is a row/column pair · both values required · one shared length unit</p>
          )}
          <div className="fvd-cal-quantity-head"><span>Quantity</span><span>Value</span><span>Unit</span><span>± 1σ</span></div>
          {fieldNames.map((name) => {
            const quantity = draft.fields[name];
            const canonical = knownFields[draft.kind]?.[name];
            const unit = quantity?.unit ?? canonical ?? "";
            const pixelIndex = PIXEL_FIELDS.indexOf(name as typeof PIXEL_FIELDS[number]);
            if (draft.kind === "acquisition" && pixelIndex >= 0) {
              const axis = pixelIndex === 0 ? "row" : "column";
              const sigmaKey = pixelIndex === 0 ? "rowSigma" : "columnSigma";
              return (
                <div className="fvd-cal-quantity-row fvd-cal-pixel-pair" key={name}>
                  <label htmlFor={`q-${name}`}>Pixel size {axis}</label>
                  <input id={`q-${name}`} type="number" min={0} step="any" value={pixelPair[axis]} onChange={(event) => updatePixelPair({ ...pixelPair, [axis]: event.target.value })} />
                  <select aria-label={`${name} unit`} value={pixelPair.unit} onChange={(event) => updatePixelPair({ ...pixelPair, unit: event.target.value })}>
                    {LENGTH_UNITS.map((item) => <option key={item}>{item}</option>)}
                  </select>
                  <input aria-label={`${name} uncertainty`} type="number" min={0} step="any" value={pixelPair[sigmaKey]} disabled={pixelPair[axis] === ""} onChange={(event) => updatePixelPair({ ...pixelPair, [sigmaKey]: event.target.value })} />
                </div>
              );
            }
            return (
              <div className="fvd-cal-quantity-row" key={name}>
                <label htmlFor={`q-${name}`}>{name.replaceAll("_", " ")}</label>
                <input id={`q-${name}`} type="number" step="any" value={quantity?.value ?? ""} onChange={(e) => onChange(withQuantity(draft, name, e.target.value, unit, quantity?.sigma == null ? "" : String(quantity.sigma)))} />
                {canonical ? <span className="unit">{canonical || "—"}</span> : <input aria-label={`${name} unit`} value={unit} onChange={(e) => onChange(withQuantity(draft, name, quantity == null ? "" : String(quantity.value), e.target.value, quantity?.sigma == null ? "" : String(quantity.sigma)))} />}
                <input aria-label={`${name} uncertainty`} type="number" min={0} step="any" value={quantity?.sigma ?? ""} disabled={!quantity} onChange={(e) => onChange(withQuantity(draft, name, String(quantity?.value ?? ""), unit, e.target.value))} />
              </div>
            );
          })}
        </section>

        <section className="fvd-cal-form-section">
          <h4>Validity</h4>
          <div className="fvd-cal-form-grid">
            <label>Valid from<input type="date" value={draft.validity.valid_from ?? ""} onChange={(e) => onChange({ ...draft, validity: { ...draft.validity, valid_from: e.target.value || null } })} /></label>
            <label>Valid through<input type="date" value={draft.validity.valid_to ?? ""} onChange={(e) => onChange({ ...draft, validity: { ...draft.validity, valid_to: e.target.value || null } })} /></label>
          </div>
          <div className="fvd-cal-range-grid">
            {(Object.keys(RANGE_LABELS) as RangeKey[]).map((key) => (
              <div className="fvd-cal-range" key={key}>
                <span>{RANGE_LABELS[key][0]} <small>{RANGE_LABELS[key][1]} · both required</small></span>
                <input aria-label={`${RANGE_LABELS[key][0]} minimum`} type="number" step="any" placeholder="Min" value={ranges[key][0]} onChange={(e) => setRange(key, 0, e.target.value)} />
                <span>to</span>
                <input aria-label={`${RANGE_LABELS[key][0]} maximum`} type="number" step="any" placeholder="Max" value={ranges[key][1]} onChange={(e) => setRange(key, 1, e.target.value)} />
              </div>
            ))}
          </div>
          <label className="fvd-cal-textarea">Validity note<textarea value={draft.validity.note} onChange={(e) => onChange({ ...draft, validity: { ...draft.validity, note: e.target.value } })} /></label>
        </section>

        <section className="fvd-cal-form-section">
          <h4>Provenance</h4>
          <div className="fvd-cal-form-grid">
            <label>Source<input value={draft.provenance.source} placeholder="Measured standard, datasheet…" onChange={(e) => onChange({ ...draft, provenance: { ...draft.provenance, source: e.target.value } })} /></label>
            <label>Date<input type="date" value={draft.provenance.date ?? ""} onChange={(e) => onChange({ ...draft, provenance: { ...draft.provenance, date: e.target.value || null } })} /></label>
            <label>Operator<input value={draft.provenance.operator} onChange={(e) => onChange({ ...draft, provenance: { ...draft.provenance, operator: e.target.value } })} /></label>
          </div>
          <label className="fvd-cal-textarea">Notes<textarea value={draft.provenance.note} onChange={(e) => onChange({ ...draft, provenance: { ...draft.provenance, note: e.target.value } })} /></label>
        </section>
      </div>
    </div>
  );
}
