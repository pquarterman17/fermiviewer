import { useEffect, useMemo, useState } from "react";

import {
  applyProfile,
  createProfile,
  deleteProfile,
  getProfileHistory,
  getProfileKinds,
  importLegacyCalibrations,
  listProfiles,
  unapplyProfile,
  updateProfile,
  type CalibrationProfile,
  type ProfileDraft,
  type ProfileKind,
} from "../../../lib/api";
import { useViewer } from "../../../store/viewer";
import ProfileDetail from "./ProfileDetail";
import ProfileEditor from "./ProfileEditor";
import ProfileLibrary from "./ProfileLibrary";
import {
  draftFromProfile,
  draftForDuplicate,
  emptyProfile,
  profileSearchText,
  spatialCalibrationImpact,
} from "./profileDraft";

const EMPTY_FIELDS: Record<ProfileKind, Record<string, string>> = {
  microscope: {}, detector: {}, camera: {}, acquisition: {},
};

interface Props { onClose: () => void }

export default function CalibrationCenter({ onClose }: Props) {
  const activeId = useViewer((state) => state.activeId);
  const activeMeta = useViewer((state) => state.activeId ? state.images[state.activeId] : null);
  const setStatus = useViewer((state) => state.setStatus);
  const [profiles, setProfiles] = useState<CalibrationProfile[]>([]);
  const [knownFields, setKnownFields] = useState(EMPTY_FIELDS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [kind, setKind] = useState<ProfileKind | "all">("all");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<ProfileDraft>(emptyProfile());
  const [history, setHistory] = useState<CalibrationProfile[] | null>(null);

  const selected = profiles.find((profile) => profile.id === selectedId) ?? null;
  const activeProfiles = activeMeta?.profiles ?? {};
  const spatialImpact = selected
    ? spatialCalibrationImpact(selected, activeMeta)
    : null;

  const refresh = (preferId?: string) => {
    setLoading(true);
    return Promise.all([listProfiles(), getProfileKinds()])
      .then(([nextProfiles, catalogue]) => {
        setProfiles(nextProfiles);
        setKnownFields(catalogue.fields);
        const nextId = preferId ?? selectedId;
        setSelectedId(
          nextProfiles.some((profile) => profile.id === nextId)
            ? nextId
            : nextProfiles[0]?.id ?? null,
        );
      })
      .catch((error: Error) => setStatus(`calibration profiles: ${error.message}`))
      .finally(() => setLoading(false));
  };

  useEffect(() => { void refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return profiles.filter((profile) =>
      (kind === "all" || profile.kind === kind) &&
      (!needle || profileSearchText(profile).includes(needle)),
    );
  }, [kind, profiles, query]);

  const acceptImage = (image: NonNullable<typeof activeMeta>) => {
    useViewer.setState((state) => ({ images: { ...state.images, [image.id]: image } }));
  };

  const save = () => {
    setBusy(true);
    const request = creating
      ? createProfile(draft)
      : updateProfile(selectedId as string, {
          name: draft.name,
          fields: draft.fields,
          text: draft.text,
          validity: draft.validity,
          provenance: draft.provenance,
        });
    request
      .then(({ profile }) => {
        setStatus(`${creating ? "created" : "updated"} profile ${profile.name} · v${profile.version}`);
        setEditing(false);
        setCreating(false);
        setHistory(null);
        return refresh(profile.id);
      })
      .catch((error: Error) => setStatus(`save profile: ${error.message}`))
      .finally(() => setBusy(false));
  };

  const apply = () => {
    if (!activeId || !selected) return;
    if (
      spatialImpact?.changes && spatialImpact.current &&
      !window.confirm(
        `Apply “${selected.name}” and replace the image pixel size (${spatialImpact.current}) with ${spatialImpact.target}?`,
      )
    ) return;
    setBusy(true);
    applyProfile(activeId, selected.id)
      .then(({ image, applicability }) => {
        acceptImage(image);
        setStatus(
          applicability.length
            ? `profile applied with ${applicability.length} warning${applicability.length === 1 ? "" : "s"}`
            : `applied ${selected.name} to ${image.name}`,
        );
      })
      .catch((error: Error) => setStatus(`apply profile: ${error.message}`))
      .finally(() => setBusy(false));
  };

  const unapply = () => {
    if (!activeId || !selected) return;
    setBusy(true);
    unapplyProfile(activeId, selected.kind)
      .then(({ image }) => {
        acceptImage(image);
        setStatus(`removed ${selected.kind} profile from ${image.name}`);
      })
      .catch((error: Error) => setStatus(`remove profile: ${error.message}`))
      .finally(() => setBusy(false));
  };

  const remove = () => {
    if (!selected || !window.confirm(`Delete “${selected.name}” and its version history? Applied snapshots and saved results will remain intact.`)) return;
    setBusy(true);
    deleteProfile(selected.id)
      .then(() => {
        setStatus(`deleted profile ${selected.name}`);
        setHistory(null);
        return refresh();
      })
      .catch((error: Error) => setStatus(`delete profile: ${error.message}`))
      .finally(() => setBusy(false));
  };

  const importLegacy = () => {
    setBusy(true);
    importLegacyCalibrations()
      .then(({ created, skipped }) => {
        setStatus(`imported ${created.length} legacy calibration${created.length === 1 ? "" : "s"}${skipped.length ? ` · ${skipped.length} already imported or malformed` : ""}`);
        return refresh(created[0]?.id);
      })
      .catch((error: Error) => setStatus(`import calibrations: ${error.message}`))
      .finally(() => setBusy(false));
  };

  return (
    <div className="fvd-cal-center">
      <header className="fvd-cal-center-topbar">
        <div><span className="fvd-cal-center-mark" aria-hidden="true">◎</span><div><h2>Calibration Center</h2><p>Profiles, provenance, and instrument context</p></div></div>
        <div className="fvd-btn-row">
          <button className="fvd-btn" disabled={busy} onClick={importLegacy}>Import legacy calibrations</button>
          <button className="fvd-icon-btn" aria-label="Close Calibration Center" title="Close (Esc)" onClick={onClose}>✕</button>
        </div>
      </header>
      <div className="fvd-cal-center-body">
        <ProfileLibrary profiles={filtered} selectedId={selectedId} activeProfiles={activeProfiles} query={query} kind={kind} loading={loading} onQuery={setQuery} onKind={setKind} onSelect={(profile) => { setSelectedId(profile.id); setEditing(false); setCreating(false); setHistory(null); }} onCreate={() => { setDraft(emptyProfile(kind === "all" ? "detector" : kind)); setCreating(true); setEditing(true); }} />
        {editing ? (
          <ProfileEditor profile={selected} draft={draft} knownFields={knownFields} creating={creating} busy={busy} onChange={setDraft} onSave={save} onCancel={() => { setEditing(false); setCreating(false); }} />
        ) : selected ? (
          <ProfileDetail
            profile={selected}
            activeImageName={activeMeta?.name ?? null}
            spatialImpact={spatialImpact}
            appliedVersion={activeProfiles[selected.kind]?.id === selected.id ? activeProfiles[selected.kind].version : null}
            applicability={activeProfiles[selected.kind]?.id === selected.id ? activeProfiles[selected.kind].applicability ?? [] : []}
            busy={busy}
            history={history}
            onApply={apply}
            onUnapply={unapply}
            onEdit={() => { setDraft(draftFromProfile(selected)); setEditing(true); setCreating(false); }}
            onDuplicate={() => { setDraft(draftForDuplicate(selected)); setEditing(true); setCreating(true); }}
            onDelete={remove}
            onHistory={() => history ? setHistory(null) : getProfileHistory(selected.id).then(setHistory).catch((error: Error) => setStatus(`profile history: ${error.message}`))}
          />
        ) : (
          <main className="fvd-cal-center-welcome"><span aria-hidden="true">◎</span><h3>Your calibration library</h3><p>Create a profile to keep instrument values, validity, uncertainty, and provenance together—and snapshot exactly what each result used.</p><button className="fvd-btn primary" onClick={() => { setDraft(emptyProfile()); setCreating(true); setEditing(true); }}>Create first profile</button></main>
        )}
      </div>
    </div>
  );
}
