import { useEffect, useState } from "react";

import {
  fetchWatchJob,
  fetchWatchStatus,
  startWatch,
  stopWatch,
  type ImageMeta,
  type BatchInputBindings,
  type BatchOperation,
  type WatchStatus,
} from "../../lib/api";
import { loadBatchRecipePresets } from "../../lib/batchRecipePresets";

const POLL_MS = 1500;

interface WatchFolderSectionProps {
  /** Called with any derived image a watch job produces — the caller
   *  wires this to the same ingestDerived the batch run uses. */
  onDerived: (metas: ImageMeta[]) => void;
  operations?: BatchOperation[];
  images?: Record<string, ImageMeta>;
  order?: string[];
}

/** "Watch folder…" — pick a saved recipe preset + a server-side directory,
 *  start/stop the folder watch, and surface its status while this section
 *  is mounted (i.e. while BatchDialog is open). Its own file per the
 *  size ratchet: BatchDialog.tsx is already near the 500-line ceiling. */
export default function WatchFolderSection({
  onDerived, operations = [], images = {}, order = [],
}: WatchFolderSectionProps) {
  const [presets] = useState(loadBatchRecipePresets);
  const [presetId, setPresetId] = useState("");
  const [dir, setDir] = useState("");
  const [status, setStatus] = useState<WatchStatus | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [inputs, setInputs] = useState<BatchInputBindings>({});

  const preset = presets.find((item) => item.id === presetId);
  const inputFields = (preset?.steps ?? []).flatMap((step, stepIndex) => {
    const operation = operations.find((candidate) => candidate.name === step.op);
    return Object.entries(step.inputs ?? {}).map(([inputName, reference]) => ({
      stepIndex,
      inputName,
      reference,
      schema: operation?.inputs?.find((candidate) => candidate.name === inputName),
    }));
  });
  const missingInputs = inputFields.some(({ reference, schema }) => {
    if (schema?.required === false) return false;
    const value = inputs[reference];
    return Array.isArray(value) ? value.length === 0 : !value;
  });
  const watching = status?.watching ?? false;
  const noPresets = presets.length === 0;
  const startDisabled = busy || watching || !preset || !dir.trim() || missingInputs;
  // A disabled Start button gave zero explanation for why it stayed dead —
  // with a directory typed but no preset chosen, or (worse) with no saved
  // presets to choose from at all. Mirror FloatTools' disabled-compare-button
  // pattern: the reason lives in data-tip/data-tip-detail, read by the
  // global TooltipLayer. While busy/watching the button's state is already
  // self-explanatory (Stop is the live action), so no tip is needed there.
  const startReason =
    busy || watching
      ? null
      : noPresets
        ? 'No saved presets yet — save a recipe as a preset with "Save new" in Recipe presets above, then choose it here.'
        : !preset
          ? "Choose a saved preset."
          : !dir.trim()
            ? "Enter a folder path."
            : missingInputs
              ? "Choose every required recipe input."
            : null;

  useEffect(() => {
    let cancelled = false;
    const resolved = new Set<string>();

    const tick = async () => {
      let next: WatchStatus;
      try {
        next = await fetchWatchStatus();
      } catch {
        return; // transient — retried next tick
      }
      if (cancelled) return;
      setStatus(next);
      for (const jobId of next.job_ids) {
        if (resolved.has(jobId)) continue;
        try {
          const job = await fetchWatchJob(jobId);
          if (job.status !== "done" && job.status !== "error") continue;
          resolved.add(jobId);
          if (job.result?.derived) onDerived([job.result.derived]);
        } catch {
          /* transient — retried next tick */
        }
      }
    };

    void tick();
    const timer = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [onDerived]);

  const start = async () => {
    if (!preset || !dir.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      if (inputFields.length) {
        await startWatch(dir.trim(), preset.steps, undefined, inputs);
      } else {
        await startWatch(dir.trim(), preset.steps);
      }
      setMessage(`Watching ${dir.trim()}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not start watch");
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    try {
      await stopWatch();
      setMessage("Stopped watching");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not stop watch");
    } finally {
      setBusy(false);
    }
  };

  const statusLine = message || (
    watching
      ? `Watching ${status?.dir} — ${status?.seen ?? 0} seen · ${status?.processed ?? 0} processed`
      : status
        ? `Not watching${status.dir ? ` (last: ${status.dir})` : ""}`
        : ""
  );

  return (
    <section className="fvd-batch-presets" aria-label="Watch folder">
      <div className="fvd-batch-preset-head">
        <span>Watch folder…</span>
        <span className="fvd-ws-note">Auto-runs a saved recipe on new files</span>
      </div>
      {inputFields.map(({ stepIndex, inputName, reference, schema }) => {
        const variadic = schema?.variadic ?? false;
        const value = inputs[reference];
        return (
          <label key={`${stepIndex}:${inputName}`} className="fvd-batch-input-row">
            <span>Step {stepIndex + 1} · {inputName.replaceAll("_", " ")}</span>
            <select
              aria-label={`Watch input ${reference}`}
              multiple={variadic}
              value={variadic ? (Array.isArray(value) ? value : []) : (typeof value === "string" ? value : "")}
              disabled={busy || watching}
              onChange={(event) => setInputs({
                ...inputs,
                [reference]: variadic
                  ? Array.from(event.currentTarget.selectedOptions, (option) => option.value)
                  : event.currentTarget.value,
              })}
            >
              {!variadic && <option value="">Choose an image…</option>}
              {order.map((id) => <option key={id} value={id}>{images[id]?.name ?? id}</option>)}
            </select>
            <code>{reference}</code>
          </label>
        );
      })}
      <div className="fvd-batch-preset-row">
        <select
          aria-label="Recipe to watch with"
          value={presetId}
          disabled={busy || watching || presets.length === 0}
          onChange={(event) => setPresetId(event.target.value)}
        >
          <option value="">Choose a preset…</option>
          {presets.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} · {item.steps.length} step
              {item.steps.length === 1 ? "" : "s"}
            </option>
          ))}
        </select>
        <input
          type="text"
          aria-label="Folder to watch"
          value={dir}
          disabled={busy || watching}
          placeholder="Folder path, e.g. C:\data\incoming"
          onChange={(event) => setDir(event.target.value)}
        />
        <span
          className="fvd-tool-wrap"
          data-tip={startReason ? "Start" : undefined}
          data-tip-detail={startReason ?? undefined}
        >
          <button
            className="fvd-btn"
            disabled={startDisabled}
            data-tip={startReason ? undefined : "Start"}
            data-tip-detail={
              startReason
                ? undefined
                : "Watch this folder and auto-run the chosen recipe on new files."
            }
            onClick={() => void start()}
          >
            Start
          </button>
        </span>
        <button className="fvd-btn" disabled={busy || !watching} onClick={() => void stop()}>
          Stop
        </button>
      </div>
      {noPresets && (
        <div className="fvd-ws-note">
          No saved presets yet. Save a recipe as a preset with “Save new” in
          Recipe presets above to enable watching.
        </div>
      )}
      {statusLine && (
        <div className="fvd-batch-preset-status" aria-live="polite">
          {statusLine}
          {status?.last_error ? ` · error: ${status.last_error}` : ""}
        </div>
      )}
    </section>
  );
}
