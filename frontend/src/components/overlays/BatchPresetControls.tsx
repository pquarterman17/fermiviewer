import { useRef, useState } from "react";

import type { BatchRecipeStep } from "../../lib/api";
import {
  batchPresetFilename,
  exportBatchRecipePreset,
  importBatchRecipePreset,
  loadBatchRecipePresets,
  saveBatchRecipePreset,
  storeBatchRecipePresets,
  type BatchRecipePreset,
} from "../../lib/batchRecipePresets";
import { downloadText } from "../../lib/resultsExport";

interface BatchPresetControlsProps {
  steps: BatchRecipeStep[];
  disabled: boolean;
  onLoad: (preset: BatchRecipePreset) => string | void;
}

function uniqueName(name: string, presets: BatchRecipePreset[]): string {
  if (!presets.some((item) => item.name === name)) return name;
  let suffix = 2;
  while (presets.some((item) => item.name === `${name} (${suffix})`)) suffix++;
  return `${name} (${suffix})`;
}

export default function BatchPresetControls({
  steps,
  disabled,
  onLoad,
}: BatchPresetControlsProps) {
  const [presets, setPresets] = useState(loadBatchRecipePresets);
  const [selectedId, setSelectedId] = useState("");
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const selected = presets.find((item) => item.id === selectedId);

  const persist = (next: BatchRecipePreset[]) => {
    storeBatchRecipePresets(next);
    setPresets(next);
  };

  const select = (id: string) => {
    setSelectedId(id);
    setName(presets.find((item) => item.id === id)?.name ?? "");
    setMessage("");
  };

  const save = () => {
    try {
      const next = saveBatchRecipePreset(
        presets,
        name,
        steps,
        selectedId || undefined,
      );
      persist(next.presets);
      setSelectedId(next.saved.id);
      setName(next.saved.name);
      setMessage(`Saved “${next.saved.name}”`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save preset");
    }
  };

  const load = () => {
    if (!selected) return;
    const error = onLoad(selected);
    setMessage(error || `Loaded “${selected.name}”`);
  };

  const remove = () => {
    if (!selected) return;
    try {
      persist(presets.filter((item) => item.id !== selected.id));
      setSelectedId("");
      setName("");
      setMessage(`Deleted “${selected.name}”`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not delete preset");
    }
  };

  const exportPreset = () => {
    if (!selected) return;
    downloadText(
      batchPresetFilename(selected.name),
      exportBatchRecipePreset(selected),
      "application/json",
    );
    setMessage(`Exported “${selected.name}”`);
  };

  const importFile = async (file: File) => {
    try {
      const imported = importBatchRecipePreset(await file.text());
      imported.name = uniqueName(imported.name, presets);
      persist([...presets, imported].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedId(imported.id);
      setName(imported.name);
      setMessage(`Imported “${imported.name}”`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not import preset");
    }
  };

  return (
    <section className="fvd-batch-presets" aria-label="Recipe presets">
      <div className="fvd-batch-preset-head">
        <span>Recipe presets</span>
        <span className="fvd-ws-note">Saved on this device</span>
      </div>
      <div className="fvd-batch-preset-row">
        <select
          aria-label="Saved recipe preset"
          value={selectedId}
          disabled={disabled || presets.length === 0}
          onChange={(event) => select(event.target.value)}
        >
          <option value="">Choose a preset…</option>
          {presets.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} · {item.steps.length} step
              {item.steps.length === 1 ? "" : "s"}
            </option>
          ))}
        </select>
        <button className="fvd-btn" disabled={disabled || !selected} onClick={load}>
          Load
        </button>
        <button
          className="fvd-btn"
          disabled={disabled || !selected}
          onClick={exportPreset}
        >
          Export
        </button>
        <button
          className="fvd-btn danger"
          disabled={disabled || !selected}
          onClick={remove}
        >
          Delete
        </button>
      </div>
      <div className="fvd-batch-preset-row">
        <input
          aria-label="Preset name"
          value={name}
          disabled={disabled}
          placeholder="Name this recipe"
          onChange={(event) => setName(event.target.value)}
        />
        <button
          className="fvd-btn"
          disabled={disabled || steps.length === 0}
          onClick={save}
        >
          {selected ? "Update preset" : "Save new"}
        </button>
        <button
          className="fvd-btn"
          disabled={disabled}
          onClick={() => {
            setSelectedId("");
            setName("");
            setMessage("");
          }}
        >
          New
        </button>
        <button
          className="fvd-btn"
          disabled={disabled}
          onClick={() => fileInput.current?.click()}
        >
          Import…
        </button>
        <input
          ref={fileInput}
          className="fvd-visually-hidden"
          type="file"
          accept=".json,.fvbatch.json,application/json"
          aria-label="Import recipe preset file"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void importFile(file);
            event.target.value = "";
          }}
        />
      </div>
      {message && (
        <div className="fvd-batch-preset-status" role="status">
          {message}
        </div>
      )}
    </section>
  );
}
