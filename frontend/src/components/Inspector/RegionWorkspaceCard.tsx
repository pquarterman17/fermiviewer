import { useMemo, useState } from "react";

import type {
  ProjectRegion,
  ProjectRegionClass,
  ProjectRegions,
} from "../../lib/api";
import {
  duplicateRegion,
  duplicateRegionSet,
  nextRegionId,
  regionSummary,
  regionVisibilityKey,
} from "../../lib/regionWorkspace";
import { useViewer } from "../../store/viewer";
import Card from "./Card";
import RegionGeometryEditor from "./RegionGeometryEditor";
import RegionMaskPreview from "./RegionMaskPreview";

const DEFAULT_CLASS_COLOR = "#8b5cf6";

export default function RegionWorkspaceCard() {
  const activeId = useViewer((state) => state.activeId);
  const activeName = useViewer((state) =>
    state.activeId ? state.images[state.activeId]?.name : undefined,
  );
  const activeShape = useViewer((state) =>
    state.activeId ? state.images[state.activeId]?.shape : undefined,
  );
  const regions = useViewer((state) => state.regions);
  const regionsLoaded = useViewer((state) => state.regionsLoaded);
  const regionsLoadError = useViewer((state) => state.regionsLoadError);
  const refreshRegions = useViewer((state) => state.refreshRegions);
  const regionUi = useViewer((state) => state.regionUi);
  const replaceRegions = useViewer((state) => state.replaceRegions);
  const selectRegion = useViewer((state) => state.selectRegion);
  const toggleSetVisibility = useViewer((state) => state.toggleRegionSetVisibility);
  const toggleRegionVisibility = useViewer((state) => state.toggleRegionVisibility);
  const setStatus = useViewer((state) => state.setStatus);
  const [pending, setPending] = useState(false);
  const [classLabel, setClassLabel] = useState("");
  const [classColor, setClassColor] = useState(DEFAULT_CLASS_COLOR);

  const imageSets = useMemo(
    () => regions.sets.filter((group) => group.image_id === activeId),
    [activeId, regions.sets],
  );
  const selectedSet =
    imageSets.find((group) => group.id === regionUi.selectedSetId) ?? imageSets[0] ?? null;
  const selectedRegion =
    selectedSet?.regions.find((region) => region.id === regionUi.selectedRegionId) ?? null;
  const otherSetCount = regions.sets.length - imageSets.length;

  if (!activeId) return null;

  if (!regionsLoaded) {
    return (
      <Card title="Analysis Regions" count={0} defaultOpen>
        <div className="fvd-region-empty" role={regionsLoadError ? "alert" : "status"}>
          <span className="fvd-region-empty-icon" aria-hidden="true">⬡</span>
          <strong>{regionsLoadError ? "Analysis regions unavailable" : "Loading analysis regions…"}</strong>
          <span>
            {regionsLoadError
              ? "The existing workspace is protected. Retry before creating or editing regions."
              : "Reading the complete server workspace before edits are enabled."}
          </span>
          {regionsLoadError && (
            <button
              className="fvd-btn fvd-region-primary"
              onClick={() => void refreshRegions().catch(() => undefined)}
            >
              Retry loading regions
            </button>
          )}
        </div>
      </Card>
    );
  }

  const commit = async (next: ProjectRegions, message: string) => {
    setPending(true);
    try {
      await replaceRegions(next);
      setStatus(message);
      return true;
    } catch (error) {
      setStatus(`region update failed: ${(error as Error).message}`);
      return false;
    } finally {
      setPending(false);
    }
  };

  const replaceSet = (updated: typeof selectedSet, message: string) => {
    if (!selectedSet || !updated) return;
    void commit({
      ...regions,
      sets: regions.sets.map((group) => group.id === selectedSet.id ? updated : group),
    }, message);
  };

  const createSet = () => {
    const id = nextRegionId("region-set", regions.sets.map((group) => group.id));
    const name = `${activeName ?? "Image"} regions`;
    void commit({
      ...regions,
      sets: [...regions.sets, { id, name, image_id: activeId, regions: [], meta: {} }],
    }, `created region set “${name}”`).then((accepted) => {
      if (accepted) selectRegion(id);
    });
  };

  const addClass = () => {
    const label = classLabel.trim();
    if (!label) return;
    const id = nextRegionId(label, regions.classes.map((entry) => entry.id));
    void commit({
      ...regions,
      classes: [...regions.classes, { id, label, color: classColor, note: null }],
    }, `added region class “${label}”`).then((accepted) => {
      if (accepted) setClassLabel("");
    });
  };

  return (
    <Card
      title="Analysis Regions"
      count={imageSets.reduce((sum, group) => sum + group.regions.length, 0)}
      defaultOpen
    >
      <div className="fvd-region-intro">
        <span>Exact masks for analysis, organized into reusable sets.</span>
        {otherSetCount > 0 && <span className="fvd-region-muted">{otherSetCount} on other images</span>}
      </div>

      {imageSets.length === 0 ? (
        <div className="fvd-region-empty">
          <span className="fvd-region-empty-icon" aria-hidden="true">⬡</span>
          <strong>No analysis regions on this image</strong>
          <span>Create a set now; polygon and lasso drawing will add precise masks here.</span>
          <button className="fvd-btn fvd-region-primary" disabled={pending} onClick={createSet}>
            Create region set
          </button>
        </div>
      ) : (
        <>
          <div className="fvd-region-toolbar">
            <button
              className="fvd-region-eye"
              aria-label={regionUi.hiddenSetIds.includes(selectedSet!.id) ? "Show set" : "Hide set"}
              aria-pressed={!regionUi.hiddenSetIds.includes(selectedSet!.id)}
              onClick={() => toggleSetVisibility(selectedSet!.id)}
            >
              {regionUi.hiddenSetIds.includes(selectedSet!.id) ? "○" : "◉"}
            </button>
            <select
              aria-label="Region set"
              value={selectedSet!.id}
              onChange={(event) => selectRegion(event.target.value)}
            >
              {imageSets.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name ?? group.id} · {group.regions.length}
                </option>
              ))}
            </select>
            <button className="fvd-icon-btn" aria-label="Create another set" title="Create another set" disabled={pending} onClick={createSet}>＋</button>
            <button
              className="fvd-icon-btn"
              aria-label="Duplicate region set"
              title="Duplicate this set"
              disabled={pending}
              onClick={() => {
                const copy = duplicateRegionSet(selectedSet!, regions);
                void commit({ ...regions, sets: [...regions.sets, copy] }, `duplicated “${selectedSet!.name ?? selectedSet!.id}”`)
                  .then((accepted) => { if (accepted) selectRegion(copy.id); });
              }}
            >
              ⧉
            </button>
            <button
              className="fvd-icon-btn fvd-region-danger"
              aria-label="Delete region set"
              title="Delete this set"
              disabled={pending}
              onClick={() => {
                if (!window.confirm(`Delete region set “${selectedSet!.name ?? selectedSet!.id}”?`)) return;
                void commit({
                  ...regions,
                  sets: regions.sets.filter((group) => group.id !== selectedSet!.id),
                }, `deleted region set “${selectedSet!.name ?? selectedSet!.id}”`)
                  .then((accepted) => { if (accepted) selectRegion(null); });
              }}
            >
              ✕
            </button>
          </div>

          <label className="fvd-region-name-field">
            <span>Set name</span>
            <input
              key={selectedSet!.id}
              defaultValue={selectedSet!.name ?? ""}
              disabled={pending}
              onBlur={(event) => {
                const name = event.target.value.trim() || null;
                if (name !== selectedSet!.name) {
                  replaceSet({ ...selectedSet!, name }, `renamed region set to “${name ?? selectedSet!.id}”`);
                }
              }}
            />
          </label>

          <RegionGeometryEditor
            imageId={activeId}
            width={activeShape?.[1] ?? 0}
            height={activeShape?.[0] ?? 0}
            regionSet={selectedSet!}
            selectedRegion={selectedRegion}
            disabled={pending}
            onChange={(updated, message) => replaceSet(updated, message)}
          />

          {selectedRegion && activeId && (
            <RegionMaskPreview
              key={`${selectedSet!.id}/${selectedRegion.id}`}
              imageId={activeId}
              setId={selectedSet!.id}
              region={selectedRegion}
            />
          )}

          {selectedSet!.regions.length === 0 ? (
            <div className="fvd-region-list-empty">This set is ready for its first precise region.</div>
          ) : (
            <div className="fvd-region-list" role="list" aria-label="Regions in selected set">
              {selectedSet!.regions.map((region) => (
                <RegionRow
                  key={region.id}
                  region={region}
                  classes={regions.classes}
                  selected={selectedRegion?.id === region.id}
                  visible={!regionUi.hiddenRegionKeys.includes(
                    regionVisibilityKey(selectedSet!.id, region.id),
                  )}
                  disabled={pending}
                  onSelect={() => selectRegion(selectedSet!.id, region.id)}
                  onToggle={() => toggleRegionVisibility(selectedSet!.id, region.id)}
                  onChange={(updated, message) => replaceSet({
                    ...selectedSet!,
                    regions: selectedSet!.regions.map((entry) => entry.id === region.id ? updated : entry),
                  }, message)}
                  onDuplicate={() => {
                    const taken = regions.sets.flatMap((group) => group.regions.map((entry) => entry.id));
                    const copy = duplicateRegion(region, taken);
                    replaceSet({ ...selectedSet!, regions: [...selectedSet!.regions, copy] }, `duplicated “${region.name ?? region.id}”`);
                  }}
                  onDelete={() => {
                    if (!window.confirm(`Delete region “${region.name ?? region.id}”?`)) return;
                    replaceSet({
                      ...selectedSet!,
                      regions: selectedSet!.regions.filter((entry) => entry.id !== region.id),
                    }, `deleted region “${region.name ?? region.id}”`);
                  }}
                />
              ))}
            </div>
          )}
        </>
      )}

      <details className="fvd-region-classes">
        <summary>Classes <span>{regions.classes.length}</span></summary>
        <div className="fvd-region-class-list">
          {regions.classes.map((entry) => (
            <ClassRow
              key={entry.id}
              entry={entry}
              disabled={pending}
              onChange={(updated) => void commit({
                ...regions,
                classes: regions.classes.map((item) => item.id === entry.id ? updated : item),
              }, `updated region class “${updated.label ?? updated.id}”`)}
              onDelete={() => {
                if (!window.confirm(`Delete class “${entry.label ?? entry.id}” and unclassify its regions?`)) return;
                void commit({
                  ...regions,
                  classes: regions.classes.filter((item) => item.id !== entry.id),
                  sets: regions.sets.map((group) => ({
                    ...group,
                    regions: group.regions.map((region) =>
                      region.region_class === entry.id ? { ...region, region_class: null } : region),
                  })),
                }, `deleted region class “${entry.label ?? entry.id}”`);
              }}
            />
          ))}
        </div>
        <div className="fvd-region-class-add">
          <input type="color" aria-label="New class color" value={classColor} onChange={(event) => setClassColor(event.target.value)} />
          <input
            value={classLabel}
            placeholder="New class name"
            onChange={(event) => setClassLabel(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") addClass(); }}
          />
          <button className="fvd-icon-btn" aria-label="Add region class" title="Add class" disabled={!classLabel.trim() || pending} onClick={addClass}>＋</button>
        </div>
      </details>
    </Card>
  );
}

interface RegionRowProps {
  region: ProjectRegion;
  classes: ProjectRegionClass[];
  selected: boolean;
  visible: boolean;
  disabled: boolean;
  onSelect: () => void;
  onToggle: () => void;
  onChange: (region: ProjectRegion, message: string) => void;
  onDuplicate: () => void;
  onDelete: () => void;
}

function RegionRow(props: RegionRowProps) {
  const classEntry = props.classes.find((entry) => entry.id === props.region.region_class);
  return (
    <div
      className={`fvd-region-row${props.selected ? " selected" : ""}`}
      role="listitem"
      tabIndex={0}
      aria-current={props.selected ? "true" : undefined}
      onClick={props.onSelect}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          props.onSelect();
        }
      }}
    >
      <button className="fvd-region-eye" aria-label={props.visible ? "Hide region" : "Show region"} aria-pressed={props.visible} onClick={(event) => { event.stopPropagation(); props.onToggle(); }}>
        {props.visible ? "●" : "○"}
      </button>
      <span className="fvd-region-swatch" style={{ background: classEntry?.color ?? "var(--accent)" }} />
      <div className="fvd-region-row-main">
        <input
          key={props.region.id}
          aria-label="Region name"
          defaultValue={props.region.name ?? ""}
          disabled={props.disabled}
          onClick={(event) => event.stopPropagation()}
          onFocus={props.onSelect}
          onBlur={(event) => {
            const name = event.target.value.trim() || null;
            if (name !== props.region.name) props.onChange({ ...props.region, name }, `renamed region to “${name ?? props.region.id}”`);
          }}
        />
        <span>{regionSummary(props.region)}</span>
      </div>
      <select
        aria-label="Region class"
        value={props.region.region_class ?? ""}
        disabled={props.disabled}
        onClick={(event) => event.stopPropagation()}
        onFocus={props.onSelect}
        onChange={(event) => props.onChange({ ...props.region, region_class: event.target.value || null }, `classified “${props.region.name ?? props.region.id}”`)}
      >
        <option value="">Unclassified</option>
        {props.classes.map((entry) => <option key={entry.id} value={entry.id}>{entry.label ?? entry.id}</option>)}
      </select>
      <button className="fvd-icon-btn" aria-label="Duplicate region" title="Duplicate region" disabled={props.disabled} onClick={(event) => { event.stopPropagation(); props.onDuplicate(); }}>⧉</button>
      <button className="fvd-icon-btn fvd-region-danger" aria-label="Delete region" title="Delete region" disabled={props.disabled} onClick={(event) => { event.stopPropagation(); props.onDelete(); }}>✕</button>
    </div>
  );
}

function ClassRow({ entry, disabled, onChange, onDelete }: {
  entry: ProjectRegionClass;
  disabled: boolean;
  onChange: (entry: ProjectRegionClass) => void;
  onDelete: () => void;
}) {
  return (
    <div className="fvd-region-class-row">
      <input type="color" aria-label={`${entry.label ?? entry.id} color`} defaultValue={entry.color ?? DEFAULT_CLASS_COLOR} disabled={disabled} onBlur={(event) => { if (event.target.value !== entry.color) onChange({ ...entry, color: event.target.value }); }} />
      <input aria-label="Class label" defaultValue={entry.label ?? ""} disabled={disabled} onBlur={(event) => { const label = event.target.value.trim() || null; if (label !== entry.label) onChange({ ...entry, label }); }} />
      <button className="fvd-icon-btn fvd-region-danger" aria-label={`Delete class ${entry.label ?? entry.id}`} title="Delete class and unclassify its regions" disabled={disabled} onClick={onDelete}>✕</button>
    </div>
  );
}
