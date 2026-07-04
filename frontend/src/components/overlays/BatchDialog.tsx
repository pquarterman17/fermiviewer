// Batch recipe processor (GUI-enhancements handoff §4a). Build an ordered
// recipe of filter/transform steps from the shared catalogue, then run it
// across the selected images (or all, if none selected). Each step's output
// feeds the next (chained applyFilter), with per-image progress; only the final
// image of each chain is registered in the library. Per-step parameters reuse
// the existing askParams modal so there is one param-entry path.

import { useRef, useState } from "react";

import { applyFilter, type ImageMeta } from "../../lib/api";
import type { ParamField } from "../../lib/params";
import { BATCH_FILTERS } from "../../lib/transformTools";
import { useViewer } from "../../store/viewer";
import { askParams } from "./ParamDialog";

interface RecipeStep {
  uid: number;
  kind: string;
  label: string;
  params: Record<string, unknown>;
}

type RunState = "pending" | "running" | "done" | "fail";

const GLYPH: Record<RunState, string> = {
  pending: "·",
  running: "…",
  done: "✓",
  fail: "✗",
};

function paramSummary(params: Record<string, unknown>): string {
  return Object.entries(params)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(" · ");
}

export default function BatchDialog() {
  const open = useViewer((s) => s.batchOpen);
  const setOpen = useViewer((s) => s.setBatchOpen);
  const selected = useViewer((s) => s.selected);
  const order = useViewer((s) => s.order);
  const images = useViewer((s) => s.images);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const setStatus = useViewer((s) => s.setStatus);

  const [steps, setSteps] = useState<RecipeStep[]>([]);
  const [progress, setProgress] = useState<Record<string, RunState>>({});
  const [running, setRunning] = useState(false);
  const uid = useRef(0);

  if (!open) return null;

  // selection drives the target set; fall back to every open image
  const targets = selected.length > 0 ? selected : order;

  const addStep = async (
    kind: string,
    label: string,
    fields?: ParamField[],
  ) => {
    const params =
      fields && fields.length ? await askParams(label, fields) : {};
    if (params === null) return; // user cancelled the param modal
    setSteps((s) => [...s, { uid: uid.current++, kind, label, params }]);
  };

  const removeStep = (u: number) =>
    setSteps((s) => s.filter((x) => x.uid !== u));

  const move = (i: number, d: -1 | 1) =>
    setSteps((s) => {
      const j = i + d;
      if (j < 0 || j >= s.length) return s;
      const next = s.slice();
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });

  const run = async () => {
    if (!steps.length || !targets.length || running) return;
    setRunning(true);
    const prog: Record<string, RunState> = {};
    targets.forEach((id) => (prog[id] = "pending"));
    setProgress({ ...prog });

    const finals: ImageMeta[] = [];
    for (const id of targets) {
      prog[id] = "running";
      setProgress({ ...prog });
      try {
        let curId = id;
        let final: ImageMeta | null = null;
        for (const step of steps) {
          final = await applyFilter(curId, step.kind, step.params);
          curId = final.id; // chain: feed this step's output to the next
        }
        if (final) finals.push(final);
        prog[id] = "done";
      } catch {
        prog[id] = "fail";
      }
      setProgress({ ...prog });
    }

    if (finals.length) ingestDerived(finals);
    setStatus(
      `batch recipe: ${finals.length}/${targets.length} ok · ` +
        `${steps.length} step${steps.length === 1 ? "" : "s"}`,
    );
    setRunning(false);
  };

  const close = () => {
    if (!running) setOpen(false);
  };

  return (
    <div className="fvd-overlay-backdrop" onMouseDown={close}>
      <div
        className="fvd-glass fvd-batch"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2>Batch recipe</h2>
        <p className="fvd-batch-sub">
          {targets.length} image{targets.length === 1 ? "" : "s"}
          {selected.length > 0 ? " selected" : " (all open)"} · {steps.length}{" "}
          step{steps.length === 1 ? "" : "s"}
        </p>

        <div className="fvd-batch-pal">
          {BATCH_FILTERS.map((f) => (
            <button
              key={f.kind}
              className="fvd-pill"
              disabled={running}
              onClick={() => void addStep(f.kind, f.label, f.fields)}
              title={`Add "${f.label}" as a batch step`}
            >
              + {f.label}
            </button>
          ))}
        </div>

        <div className="fvd-batch-recipe">
          {steps.length === 0 ? (
            <div className="fvd-batch-empty">
              Add steps above — they run top-to-bottom on each image.
            </div>
          ) : (
            steps.map((s, i) => (
              <div key={s.uid} className="fvd-batch-step">
                <span className="n">{i + 1}</span>
                <span className="lbl">{s.label}</span>
                <span className="prm">{paramSummary(s.params)}</span>
                <button
                  className="mv"
                  disabled={running || i === 0}
                  onClick={() => move(i, -1)}
                  title="Move up"
                >
                  ↑
                </button>
                <button
                  className="mv"
                  disabled={running || i === steps.length - 1}
                  onClick={() => move(i, 1)}
                  title="Move down"
                >
                  ↓
                </button>
                <button
                  className="rm"
                  disabled={running}
                  onClick={() => removeStep(s.uid)}
                  title="Remove step"
                >
                  ✕
                </button>
              </div>
            ))
          )}
        </div>

        {Object.keys(progress).length > 0 && (
          <div className="fvd-batch-prog">
            {targets.map((id) => {
              const st = progress[id] ?? "pending";
              return (
                <div key={id} className="row">
                  <span className={`st ${st}`}>{GLYPH[st]}</span>
                  <span className="nm">{images[id]?.name ?? id}</span>
                </div>
              );
            })}
          </div>
        )}

        <div className="fvd-btn-row">
          <button
            className="fvd-btn"
            onClick={close}
            disabled={running}
            title="Close the batch dialog (Esc)"
          >
            Close
          </button>
          <button
            className="fvd-btn primary"
            onClick={() => void run()}
            disabled={running || steps.length === 0 || targets.length === 0}
            title="Run the recipe on all target images"
          >
            {running ? "Running…" : `Run batch (${targets.length})`}
          </button>
        </div>
      </div>
    </div>
  );
}
