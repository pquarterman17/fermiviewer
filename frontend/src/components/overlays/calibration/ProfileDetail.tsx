import type { CalibrationProfile } from "../../../lib/api";
import { compactDate, type SpatialCalibrationImpact } from "./profileDraft";

interface Props {
  profile: CalibrationProfile;
  appliedVersion: number | null;
  applicability: string[];
  activeImageName: string | null;
  spatialImpact: SpatialCalibrationImpact | null;
  busy: boolean;
  history: CalibrationProfile[] | null;
  onApply: () => void;
  onUnapply: () => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onHistory: () => void;
}

function title(value: string): string {
  return value.replaceAll("_", " ");
}

export default function ProfileDetail({
  profile,
  appliedVersion,
  applicability,
  activeImageName,
  spatialImpact,
  busy,
  history,
  onApply,
  onUnapply,
  onEdit,
  onDuplicate,
  onDelete,
  onHistory,
}: Props) {
  const isApplied = appliedVersion != null;
  const stale = isApplied && appliedVersion !== profile.version;
  return (
    <article className="fvd-cal-center-detail">
      <header className="fvd-cal-center-detail-head">
        <div>
          <span className="fvd-cal-center-eyebrow">{profile.kind} profile</span>
          <h3>{profile.name}</h3>
          <p>Version {profile.version} · updated {compactDate(profile.updated_at)}</p>
        </div>
        <div className="fvd-btn-row">
          <button className="fvd-btn" onClick={onDuplicate}>Duplicate</button>
          <button className="fvd-btn" onClick={onEdit}>Edit</button>
        </div>
      </header>

      {activeImageName ? (
        <section className={`fvd-cal-apply-card${applicability.length ? " warn" : ""}`}>
          <div>
            <span className="fvd-cal-center-eyebrow">Active image</span>
            <strong>{activeImageName}</strong>
            <small>
              {isApplied
                ? stale ? `Applied at v${appliedVersion}; current is v${profile.version}` : `Profile v${appliedVersion} applied`
                : "This profile is not applied"}
            </small>
            {spatialImpact && (
              <small className="fvd-cal-spatial-impact">
                {isApplied
                  ? "Removing the profile keeps its pixel calibration. Clear it in Inspector → Calibration."
                  : spatialImpact.current && !spatialImpact.changes
                    ? `Pixel size ${spatialImpact.target} matches the image calibration.`
                    : `Will set pixel size to ${spatialImpact.target}${spatialImpact.current ? `, replacing ${spatialImpact.current}` : ""}.`}
              </small>
            )}
          </div>
          {isApplied ? (
            <button className="fvd-btn" disabled={busy} onClick={onUnapply}>Remove profile</button>
          ) : (
            <button className="fvd-btn primary" disabled={busy} onClick={onApply}>Apply to image</button>
          )}
          {applicability.length > 0 && (
            <ul className="fvd-cal-warning-list" aria-label="Applicability warnings">
              {applicability.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          )}
        </section>
      ) : <div className="fvd-cal-no-image">Open an image to apply this profile.</div>}

      <div className="fvd-cal-detail-scroll">
        <section className="fvd-cal-detail-section">
          <h4>Calibration values</h4>
          {Object.keys(profile.fields).length ? (
            <dl className="fvd-cal-values">
              {Object.entries(profile.fields).map(([name, quantity]) => (
                <div key={name}>
                  <dt>{title(name)}</dt>
                  <dd>{quantity.value} {quantity.unit}{quantity.sigma != null && <small> ± {quantity.sigma}</small>}</dd>
                </div>
              ))}
            </dl>
          ) : <p className="fvd-text-faint">No quantitative values recorded.</p>}
        </section>

        <section className="fvd-cal-detail-section">
          <h4>Identity & provenance</h4>
          <dl className="fvd-cal-values compact">
            {Object.entries(profile.text).filter(([, value]) => value).map(([name, value]) => <div key={name}><dt>{title(name)}</dt><dd>{value}</dd></div>)}
            <div><dt>Source</dt><dd>{profile.provenance.source || "Not recorded"}</dd></div>
            <div><dt>Established</dt><dd>{profile.provenance.date ?? "Not recorded"}</dd></div>
            <div><dt>Operator</dt><dd>{profile.provenance.operator || "Not recorded"}</dd></div>
          </dl>
          {profile.provenance.note && <p className="fvd-cal-note">{profile.provenance.note}</p>}
        </section>

        <section className="fvd-cal-detail-section">
          <div className="fvd-cal-form-title">
            <h4>Version history</h4>
            <button className="fvd-link-btn" onClick={onHistory}>{history ? "Hide" : "Show history"}</button>
          </div>
          {history && <ol className="fvd-cal-history">{[...history].reverse().map((version) => <li key={version.version}><strong>v{version.version}</strong><span>{compactDate(version.updated_at)}</span><small>{version.provenance.source || "No source"}</small></li>)}</ol>}
        </section>
      </div>

      <footer className="fvd-cal-detail-footer">
        <span>ID {profile.id}</span>
        <button className="fvd-link-btn danger" onClick={onDelete}>Delete profile</button>
      </footer>
    </article>
  );
}
