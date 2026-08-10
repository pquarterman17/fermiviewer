// Per-sample parameter editor (W4 item 23) — the named, numeric-with-unit
// parameters that item 24's result-vs-parameter roll-up (lib/projectCompare.ts)
// plots against. Reuses the shared ParamFieldRow widget
// (components/overlays/ParamFields.tsx) so a sample's parameter form looks
// and behaves exactly like every other parameter surface in the app
// (ParamDialog, TransformPanel) — same number-coerce-on-blur behaviour, same
// row chrome.
//
// The ONE documented convention (lib/groups.ts GroupParam, mirrored in the
// project manifest schema, docs/schema/fvp-v2.schema.json): `value` is a
// finite number for anything meant to be plotted, with an optional `unit`
// string; string/boolean values are categorical and are never coerced to a
// number — lib/projectCompare.ts reports categorical values as excluded
// from the plot instead of silently dropping or coercing them. A unit input
// is only offered for numeric parameters, since a unit on a categorical
// value has no meaning.
//
// Standalone component, deliberately not wired into a sample section's
// header: Library/SampleSection.tsx is owned by another in-flight change on
// this branch. It is reachable today via ProjectComparePanel (Analysis ▸
// Samples ▸ Compare Samples…), which mounts it for the currently selected
// sample. The natural long-term home is a small "Edit Params" icon button in
// SampleSection's header (frontend/src/components/Library/SampleSection.tsx,
// the <button className="fvd-sample-head"> block around lines 73-82) next to
// the count badge, opening this editor for that section's groupId.

import { useState } from "react";

import type { GroupParam, GroupParams } from "../../lib/groups";
import type { ParamField } from "../../lib/params";
import { useViewer } from "../../store/viewer";
import Icon from "../icons/Icon";
import { ParamFieldRow } from "../overlays/ParamFields";

type NewParamType = "number" | "text" | "boolean";

function fieldTypeOf(value: number | string | boolean): ParamField["type"] {
  if (typeof value === "number") return "number";
  if (typeof value === "boolean") return "boolean";
  return "text";
}

function defaultForType(type: NewParamType): number | string | boolean {
  if (type === "number") return 0;
  if (type === "boolean") return false;
  return "";
}

export default function SampleParamsEditor({ groupId }: { groupId: string }) {
  const group = useViewer((s) => s.imageGroups.find((g) => g.id === groupId));
  const setGroupParams = useViewer((s) => s.setGroupParams);
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState<NewParamType>("number");
  const [newValue, setNewValue] = useState<number | string | boolean>(0);
  const [newUnit, setNewUnit] = useState("");

  if (!group) return null;
  const params: GroupParams = group.params ?? {};
  const names = Object.keys(params).sort();

  const write = (next: GroupParams) => setGroupParams(group.id, next);

  const updateValue = (name: string, value: number | string | boolean) =>
    write({ ...params, [name]: { ...params[name], value } });

  const updateUnit = (name: string, unit: string) =>
    write({ ...params, [name]: { ...params[name], unit: unit.trim() || null } });

  const remove = (name: string) => {
    const next = { ...params };
    delete next[name];
    write(next);
  };

  const addParam = () => {
    const name = newName.trim();
    if (!name || name in params) return;
    const param: GroupParam = {
      value: newValue,
      unit: newType === "number" && newUnit.trim() ? newUnit.trim() : null,
    };
    write({ ...params, [name]: param });
    setNewName("");
    setNewValue(defaultForType(newType));
    setNewUnit("");
  };

  return (
    <div className="fvd-sample-params" data-testid="sample-params-editor">
      <div className="fvd-ws-note">
        Parameters for <strong>{group.name}</strong> — one numeric value plus
        an optional unit per row. Only numeric parameters can be plotted;
        text/boolean values are categorical.
      </div>
      {names.length === 0 && (
        <div className="fvd-ws-note" style={{ color: "var(--text-faint)" }}>
          No parameters yet — add one below (e.g. "anneal_temp", 450, "degC").
        </div>
      )}
      {names.map((name) => {
        const p = params[name];
        const field: ParamField = {
          key: name,
          label: name,
          type: fieldTypeOf(p.value),
          default: p.value,
        };
        return (
          <div key={name} className="fvd-ws-row">
            <ParamFieldRow field={field} value={p.value} onChange={(v) => updateValue(name, v)} />
            {field.type === "number" && (
              <input
                aria-label={`${name} unit`}
                placeholder="unit"
                value={p.unit ?? ""}
                onChange={(e) => updateUnit(name, e.target.value)}
                style={{ width: 64 }}
              />
            )}
            <button
              className="fvd-icon-btn"
              aria-label={`Remove ${name}`}
              title={`Remove ${name}`}
              onClick={() => remove(name)}
            >
              <Icon name="close" />
            </button>
          </div>
        );
      })}
      <div className="fvd-ws-row">
        <input
          aria-label="New parameter name"
          placeholder="name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          style={{ width: 96 }}
        />
        <select
          aria-label="New parameter type"
          value={newType}
          onChange={(e) => {
            const t = e.target.value as NewParamType;
            setNewType(t);
            setNewValue(defaultForType(t));
            if (t !== "number") setNewUnit("");
          }}
        >
          <option value="number">number</option>
          <option value="text">text</option>
          <option value="boolean">boolean</option>
        </select>
        <ParamFieldRow
          field={{ key: "__new", label: "value", type: newType, default: defaultForType(newType) }}
          value={newValue}
          onChange={setNewValue}
        />
        {newType === "number" && (
          <input
            aria-label="New parameter unit"
            placeholder="unit"
            value={newUnit}
            onChange={(e) => setNewUnit(e.target.value)}
            style={{ width: 64 }}
          />
        )}
        <button
          className="fvd-btn"
          title="Add this parameter to the sample"
          onClick={addParam}
          disabled={!newName.trim()}
        >
          <Icon name="plus" /> Add
        </button>
      </div>
    </div>
  );
}
