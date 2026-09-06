import type {
  CalibrationProfile,
  ProfileDraft,
  ProfileKind,
} from "../../../lib/api";
import { KIND_LABEL, PROFILE_KINDS, TEXT_FIELDS, withQuantity } from "./profileDraft";

type RangeKey = "beam_energy_kev" | "magnification" | "camera_length_mm";

const RANGE_LABELS: Record<RangeKey, [string, string]> = {
  beam_energy_kev: ["Beam energy", "keV"],
  magnification: ["Magnification", "×"],
  camera_length_mm: ["Camera length", "mm"],
};

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
  const fieldNames = Array.from(
    new Set([...Object.keys(knownFields[draft.kind] ?? {}), ...Object.keys(draft.fields)]),
  );
  const textNames = Array.from(
    new Set([...TEXT_FIELDS[draft.kind], ...Object.keys(draft.text)]),
  );

  const setRange = (key: RangeKey, index: 0 | 1, raw: string) => {
    if (raw === "") {
      onChange({
        ...draft,
        validity: { ...draft.validity, [key]: null },
      });
      return;
    }
    const value = Number(raw);
    const current = draft.validity[key] ?? [value, value];
    const next: [number, number] = [...current];
    next[index] = value;
    onChange({
      ...draft,
      validity: { ...draft.validity, [key]: next },
    });
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
              <label key={name}>{name.replaceAll("_", " ")}<input value={draft.text[name] ?? ""} onChange={(e) => onChange({ ...draft, text: { ...draft.text, [name]: e.target.value } })} /></label>
            ))}
          </div>
        </section>

        <section className="fvd-cal-form-section">
          <div className="fvd-cal-form-title"><h4>Calibration values</h4><span>Leave unused values blank</span></div>
          <div className="fvd-cal-quantity-head"><span>Quantity</span><span>Value</span><span>Unit</span><span>± 1σ</span></div>
          {fieldNames.map((name) => {
            const quantity = draft.fields[name];
            const canonical = knownFields[draft.kind]?.[name];
            const unit = quantity?.unit ?? canonical ?? "";
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
                <span>{RANGE_LABELS[key][0]} <small>{RANGE_LABELS[key][1]}</small></span>
                <input aria-label={`${RANGE_LABELS[key][0]} minimum`} type="number" step="any" placeholder="Min" value={draft.validity[key]?.[0] ?? ""} onChange={(e) => setRange(key, 0, e.target.value)} />
                <span>to</span>
                <input aria-label={`${RANGE_LABELS[key][0]} maximum`} type="number" step="any" placeholder="Max" value={draft.validity[key]?.[1] ?? ""} onChange={(e) => setRange(key, 1, e.target.value)} />
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
