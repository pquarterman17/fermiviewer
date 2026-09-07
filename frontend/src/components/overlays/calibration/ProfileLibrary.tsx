import type { CalibrationProfile, ProfileKind } from "../../../lib/api";
import { compactDate, KIND_LABEL, PROFILE_KINDS } from "./profileDraft";

interface Props {
  profiles: CalibrationProfile[];
  selectedId: string | null;
  activeProfiles: Record<string, { id: string; version: number }>;
  query: string;
  kind: ProfileKind | "all";
  loading: boolean;
  onQuery: (value: string) => void;
  onKind: (kind: ProfileKind | "all") => void;
  onSelect: (profile: CalibrationProfile) => void;
  onCreate: () => void;
}

export default function ProfileLibrary({
  profiles,
  selectedId,
  activeProfiles,
  query,
  kind,
  loading,
  onQuery,
  onKind,
  onSelect,
  onCreate,
}: Props) {
  return (
    <aside className="fvd-cal-center-library" aria-label="Calibration profiles">
      <div className="fvd-cal-center-search">
        <span aria-hidden="true">⌕</span>
        <input
          aria-label="Search calibration profiles"
          placeholder="Search profiles…"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
        />
      </div>
      <div className="fvd-cal-kind-tabs" role="group" aria-label="Profile type">
        <button aria-pressed={kind === "all"} onClick={() => onKind("all")}>All</button>
        {PROFILE_KINDS.map((item) => (
          <button key={item} aria-pressed={kind === item} onClick={() => onKind(item)} title={KIND_LABEL[item]}>
            {item === "microscope" ? "Scope" : KIND_LABEL[item].slice(0, -1)}
          </button>
        ))}
      </div>
      <div className="fvd-cal-profile-list">
        {loading ? (
          <div className="fvd-cal-center-empty">Loading profiles…</div>
        ) : profiles.length === 0 ? (
          <div className="fvd-cal-center-empty">
            <strong>No matching profiles</strong>
            <span>Create one or import your legacy pixel calibrations.</span>
          </div>
        ) : profiles.map((profile) => {
          const applied = activeProfiles[profile.kind];
          const isApplied = applied?.id === profile.id;
          return (
            <button
              className="fvd-cal-profile-row"
              data-selected={selectedId === profile.id}
              key={profile.id}
              onClick={() => onSelect(profile)}
            >
              <span className={`fvd-cal-kind-dot ${profile.kind}`} aria-hidden="true" />
              <span className="copy">
                <strong>{profile.name}</strong>
                <small>{profile.kind} · v{profile.version} · {compactDate(profile.updated_at)}</small>
              </span>
              {isApplied && <span className="fvd-cal-applied-pill">Applied</span>}
            </button>
          );
        })}
      </div>
      <button className="fvd-btn primary fvd-cal-new" onClick={onCreate}>＋ New profile</button>
    </aside>
  );
}
