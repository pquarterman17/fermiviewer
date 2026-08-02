import { useEffect, useState } from "react";

import {
  fetchWatchJob,
  fetchWatchStatus,
  startWatch,
  stopWatch,
  type ImageMeta,
  type WatchStatus,
} from "../../lib/api";
import { loadBatchRecipePresets } from "../../lib/batchRecipePresets";

const POLL_MS = 1500;

interface WatchFolderSectionProps {
  /** Called with any derived image a watch job produces — the caller
   *  wires this to the same ingestDerived the batch run uses. */
  onDerived: (metas: ImageMeta[]) => void;
}

/** "Watch folder…" — pick a saved recipe preset + a server-side directory,
 *  start/stop the folder watch, and surface its status while this section
 *  is mounted (i.e. while BatchDialog is open). Its own file per the
 *  size ratchet: BatchDialog.tsx is already near the 500-line ceiling. */
export default function WatchFolderSection({ onDerived }: WatchFolderSectionProps) {
  const [presets] = useState(loadBatchRecipePresets);
  const [presetId, setPresetId] = useState("");
  const [dir, setDir] = useState("");
  const [status, setStatus] = useState<WatchStatus | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const preset = presets.find((item) => item.id === presetId);
  const watching = status?.watching ?? false;

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
      await startWatch(dir.trim(), preset.steps);
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
        <button
          className="fvd-btn"
          disabled={busy || watching || !preset || !dir.trim()}
          onClick={() => void start()}
        >
          Start
        </button>
        <button className="fvd-btn" disabled={busy || !watching} onClick={() => void stop()}>
          Stop
        </button>
      </div>
      {statusLine && (
        <div className="fvd-batch-preset-status" aria-live="polite">
          {statusLine}
          {status?.last_error ? ` · error: ${status.last_error}` : ""}
        </div>
      )}
    </section>
  );
}
