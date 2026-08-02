import { useEffect, useRef, useState } from "react";

import {
  fetchBatchOperations,
  runBatchRecipe,
  type BatchOperation,
  type BatchRecipeStep,
  type BatchRunResult,
} from "../../lib/api";
import type { BatchRecipePreset } from "../../lib/batchRecipePresets";
import type { ParamField } from "../../lib/params";
import {
  downloadCsv,
  downloadJson,
  tableToCsv,
  tableToJson,
  type Cell,
} from "../../lib/resultsExport";
import { askParams } from "../../store/params";
import { useViewer } from "../../store/viewer";
import BatchPresetControls from "./BatchPresetControls";
import ModalDialog from "./ModalDialog";
import WatchFolderSection from "./WatchFolderSection";

interface RecipeStep extends BatchRecipeStep {
  uid: number;
  label: string;
  produces: BatchOperation["produces"];
}

type RunState = "pending" | "running" | "done" | "fail";

const GLYPH: Record<RunState, string> = {
  pending: "·",
  running: "…",
  done: "✓",
  fail: "×",
};

function paramSummary(params: Record<string, unknown>): string {
  return Object.entries(params)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(" · ");
}

function paramFields(operation: BatchOperation): ParamField[] {
  return operation.params.map((param) => {
    const fallback =
      param.default ??
      (param.type === "bool" ? false : param.type === "str" ? "" : 0);
    if (param.choices) {
      return {
        key: param.name,
        label: param.name.replaceAll("_", " "),
        type: "select",
        default: String(fallback),
        options: param.choices.map(String),
        hint: param.doc,
      };
    }
    return {
      key: param.name,
      label: param.name.replaceAll("_", " "),
      type:
        param.type === "bool"
          ? "boolean"
          : param.type === "str"
            ? "text"
            : "number",
      default: fallback as number | string | boolean,
      hint: [
        param.doc,
        param.minimum != null ? `min ${param.minimum}` : "",
        param.maximum != null ? `max ${param.maximum}` : "",
      ].filter(Boolean).join(" · "),
    };
  });
}

function flatten(
  value: Record<string, unknown>,
  prefix: string,
): Record<string, Cell> {
  const out: Record<string, Cell> = {};
  for (const [key, item] of Object.entries(value)) {
    const column = `${prefix}.${key}`;
    if (
      item == null ||
      typeof item === "string" ||
      typeof item === "number"
    ) {
      out[column] = item as Cell;
    } else {
      out[column] = JSON.stringify(item);
    }
  }
  return out;
}

export function batchResultTable(result: BatchRunResult): {
  columns: string[];
  rows: Cell[][];
} {
  const records = result.outputs.map((output) => {
    const record: Record<string, Cell> = {
      input: output.name,
      status: output.status,
      error: output.error ?? "",
      derived: output.derived?.name ?? "",
    };
    for (const value of output.values) {
      Object.assign(record, flatten(value.value, value.op));
    }
    return record;
  });
  const fixed = ["input", "status", "error", "derived"];
  const extras = [...new Set(records.flatMap((record) => Object.keys(record)))]
    .filter((key) => !fixed.includes(key))
    .sort();
  const columns = [...fixed, ...extras];
  return {
    columns,
    rows: records.map((record) => columns.map((column) => record[column] ?? null)),
  };
}

export default function BatchDialog() {
  const open = useViewer((s) => s.batchOpen);
  const setOpen = useViewer((s) => s.setBatchOpen);
  const selected = useViewer((s) => s.selected);
  const order = useViewer((s) => s.order);
  const images = useViewer((s) => s.images);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const setStatus = useViewer((s) => s.setStatus);
  const [operations, setOperations] = useState<BatchOperation[]>([]);
  const [schemaError, setSchemaError] = useState("");
  const [steps, setSteps] = useState<RecipeStep[]>([]);
  const [progress, setProgress] = useState<Record<string, RunState>>({});
  const [progressText, setProgressText] = useState("");
  const [progressValue, setProgressValue] = useState(0);
  const [result, setResult] = useState<BatchRunResult | null>(null);
  const [running, setRunning] = useState(false);
  const uid = useRef(0);

  useEffect(() => {
    if (!open || operations.length > 0) return;
    fetchBatchOperations()
      .then(setOperations)
      .catch((error: Error) => setSchemaError(error.message));
  }, [open, operations.length]);

  if (!open) return null;
  const targets = selected.length > 0 ? selected : order;
  const groups = operations.reduce<Record<string, BatchOperation[]>>(
    (current, operation) => {
      (current[operation.category] ??= []).push(operation);
      return current;
    },
    {},
  );

  const addStep = async (operation: BatchOperation) => {
    const fields = paramFields(operation);
    const params = fields.length
      ? await askParams(operation.summary, fields)
      : {};
    if (params === null) return;
    setSteps((current) => [
      ...current,
      {
        uid: uid.current++,
        op: operation.name,
        label: operation.summary,
        produces: operation.produces,
        params,
      },
    ]);
  };

  const move = (index: number, direction: -1 | 1) =>
    setSteps((current) => {
      const destination = index + direction;
      if (destination < 0 || destination >= current.length) return current;
      const next = current.slice();
      [next[index], next[destination]] = [next[destination], next[index]];
      return next;
    });

  const loadPreset = (preset: BatchRecipePreset): string | void => {
    const byName = new Map(
      operations.map((operation) => [operation.name, operation]),
    );
    const missing = preset.steps
      .map((step) => step.op)
      .filter((name) => !byName.has(name));
    if (missing.length) {
      return `Unavailable operation${missing.length === 1 ? "" : "s"}: ${missing.join(", ")}`;
    }
    setSteps(
      preset.steps.map((step) => {
        const operation = byName.get(step.op)!;
        return {
          ...step,
          uid: uid.current++,
          label: operation.summary,
          produces: operation.produces,
        };
      }),
    );
    setProgress({});
    setResult(null);
  };

  const run = async () => {
    if (!steps.length || !targets.length || running) return;
    const states = Object.fromEntries(
      targets.map((imageId) => [imageId, "pending" as RunState]),
    );
    states[targets[0]] = "running";
    setProgress(states);
    setProgressValue(0);
    setProgressText("Queued");
    setResult(null);
    setRunning(true);
    try {
      const next = await runBatchRecipe(
        targets,
        steps.map(({ op, params }) => ({ op, params })),
        (fraction, message) => {
          setProgressValue(fraction);
          setProgressText(message);
          const completeUnits = Math.floor(fraction * targets.length * steps.length);
          const currentIndex = Math.min(
            targets.length - 1,
            Math.floor(completeUnits / steps.length),
          );
          setProgress((previous) =>
            Object.fromEntries(
              targets.map((id, index) => [
                id,
                index < currentIndex
                  ? "done"
                  : index === currentIndex
                    ? "running"
                    : previous[id] ?? "pending",
              ]),
            ),
          );
        },
      );
      setResult(next);
      setProgress(
        Object.fromEntries(
          next.outputs.map((output) => [
            output.image_id,
            output.status === "done" ? "done" : "fail",
          ]),
        ),
      );
      const derived = next.outputs
        .map((output) => output.derived)
        .filter((meta) => meta !== null);
      if (derived.length) ingestDerived(derived);
      setProgressValue(1);
      setProgressText(`${next.succeeded} succeeded · ${next.failed} failed`);
      setStatus(
        `batch recipe: ${next.succeeded}/${next.outputs.length} succeeded · ` +
          `${steps.length} step${steps.length === 1 ? "" : "s"}`,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setProgressText(message);
      setStatus(`batch recipe: ${message}`);
    } finally {
      setRunning(false);
    }
  };

  const exportResult = (format: "csv" | "json") => {
    if (!result) return;
    const table = batchResultTable(result);
    const provenance = {
      analysis: "Batch recipe",
      params: { version: result.version, steps: result.steps },
    };
    if (format === "csv") {
      downloadCsv(
        "fermiviewer_batch_results.csv",
        tableToCsv(table.columns, table.rows, provenance),
      );
    } else {
      downloadJson(
        "fermiviewer_batch_results.json",
        tableToJson(table.columns, table.rows, provenance),
      );
    }
  };

  return (
    <ModalDialog
      ariaLabel="Batch recipe"
      className="fvd-batch"
      onClose={() => !running && setOpen(false)}
    >
      <h2>Batch recipe</h2>
      <p className="fvd-batch-sub">
        {targets.length} image{targets.length === 1 ? "" : "s"}
        {selected.length > 0 ? " selected" : " (all open)"} · {steps.length}{" "}
        step{steps.length === 1 ? "" : "s"}
      </p>

      <BatchPresetControls
        steps={steps.map(({ op, params }) => ({ op, params }))}
        disabled={running || operations.length === 0}
        onLoad={loadPreset}
      />

      <WatchFolderSection onDerived={ingestDerived} />

      {schemaError && <div className="fvd-batch-empty">{schemaError}</div>}
      {Object.entries(groups).map(([category, entries]) => (
        <section key={category}>
          <div className="fvd-ws-note">{category}</div>
          <div className="fvd-batch-pal">
            {entries.map((operation) => (
              <button
                key={operation.name}
                className="fvd-pill"
                disabled={running}
                onClick={() => void addStep(operation)}
                title={`${operation.summary} · produces ${operation.produces}`}
              >
                + {operation.summary}
              </button>
            ))}
          </div>
        </section>
      ))}

      <div className="fvd-batch-recipe">
        {steps.length === 0 ? (
          <div className="fvd-batch-empty">
            Add image or analysis steps — they run top-to-bottom on each input.
          </div>
        ) : (
          steps.map((step, index) => (
            <div key={step.uid} className="fvd-batch-step">
              <span className="n">{index + 1}</span>
              <span className="lbl">{step.label}</span>
              <span className="prm">
                {step.produces} {paramSummary(step.params)}
              </span>
              <button
                className="mv"
                disabled={running || index === 0}
                onClick={() => move(index, -1)}
                title="Move up"
              >
                ↑
              </button>
              <button
                className="mv"
                disabled={running || index === steps.length - 1}
                onClick={() => move(index, 1)}
                title="Move down"
              >
                ↓
              </button>
              <button
                className="rm"
                disabled={running}
                onClick={() =>
                  setSteps((current) =>
                    current.filter((candidate) => candidate.uid !== step.uid),
                  )
                }
                title="Remove step"
              >
                ×
              </button>
            </div>
          ))
        )}
      </div>

      {Object.keys(progress).length > 0 && (
        <>
          <progress max="1" value={progressValue} style={{ width: "100%" }} />
          <div className="fvd-ws-note" role="status">{progressText}</div>
          <div className="fvd-batch-prog">
            {targets.map((id) => {
              const state = progress[id] ?? "pending";
              const error = result?.outputs.find(
                (output) => output.image_id === id,
              )?.error;
              return (
                <div key={id} className="row" title={error}>
                  <span className={`st ${state}`}>{GLYPH[state]}</span>
                  <span className="nm">{images[id]?.name ?? id}</span>
                </div>
              );
            })}
          </div>
        </>
      )}

      {result && <BatchResults result={result} />}
      {result && (
        <div className="fvd-btn-row">
          <button className="fvd-btn" onClick={() => exportResult("csv")}>
            Export CSV
          </button>
          <button className="fvd-btn" onClick={() => exportResult("json")}>
            Export JSON
          </button>
        </div>
      )}

      <div className="fvd-btn-row">
        <button
          className="fvd-btn"
          onClick={() => setOpen(false)}
          disabled={running}
        >
          Close
        </button>
        <button
          className="fvd-btn primary"
          onClick={() => void run()}
          disabled={running || steps.length === 0 || targets.length === 0}
        >
          {running ? "Running…" : `Run batch (${targets.length})`}
        </button>
      </div>
    </ModalDialog>
  );
}

function BatchResults({ result }: { result: BatchRunResult }) {
  const table = batchResultTable(result);
  return (
    <div style={{ overflow: "auto", maxHeight: 230 }}>
      <table className="fvd-ws-table">
        <thead>
          <tr>
            {table.columns.map((column) => <th key={column}>{column}</th>)}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, index) => (
            <tr key={result.outputs[index].image_id}>
              {row.map((value, column) => (
                <td key={table.columns[column]}>
                  {typeof value === "number"
                    ? Number(value.toPrecision(5))
                    : (value ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
