import { useEffect, useRef, useState } from "react";

import {
  fetchBatchOperations,
  runBatchRecipe,
  type BatchOperation,
  type BatchInputBindings,
  type BatchRunResult,
} from "../../lib/api";
import type { BatchRecipePreset } from "../../lib/batchRecipePresets";
import {
  downloadCsv,
  downloadJson,
  tableToCsv,
  tableToJson,
} from "../../lib/resultsExport";
import { askParams } from "../../store/params";
import { useViewer } from "../../store/viewer";
import BatchPresetControls from "./BatchPresetControls";
import BatchResults, { batchResultTable } from "./BatchResults";
import RecipeInputs, {
  allocateInputReferences,
  paramFields,
  parsedParams,
  recipeErrors,
  recipeInputNames,
  type RecipeStep,
} from "./BatchRecipeInputs";
import MacroBridge from "./MacroBridge";
import ModalDialog from "./ModalDialog";
import WatchFolderSection from "./WatchFolderSection";

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

export { batchResultTable };

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
  const [inputBindings, setInputBindings] = useState<BatchInputBindings>({});
  const [operationSearch, setOperationSearch] = useState("");
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
  const visibleOperations = operations.filter((operation) =>
    `${operation.name} ${operation.summary} ${operation.category}`
      .toLowerCase()
      .includes(operationSearch.trim().toLowerCase()),
  );
  const groups = visibleOperations.reduce<Record<string, BatchOperation[]>>(
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
    let converted: Record<string, unknown>;
    try {
      converted = parsedParams(operation, params);
    } catch (error) {
      setSchemaError(error instanceof Error ? error.message : String(error));
      return;
    }
    setSchemaError("");
    setSteps((current) => {
      const used = recipeInputNames(current);
      const inputs = allocateInputReferences(operation.inputs ?? [], used);
      return [...current, {
        uid: uid.current++,
        op: operation.name,
        label: operation.summary,
        produces: operation.produces,
        params: converted,
        inputSchemas: operation.inputs ?? [],
        ...(Object.keys(inputs).length ? { inputs } : {}),
      }];
    });
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
    const used = new Set<string>();
    setSteps(
      preset.steps.map((step) => {
        const operation = byName.get(step.op)!;
        const inputs = allocateInputReferences(
          operation.inputs ?? [], used, step.inputs,
        );
        return {
          ...step,
          ...(Object.keys(inputs).length ? { inputs } : {}),
          uid: uid.current++,
          label: operation.summary,
          produces: operation.produces,
          inputSchemas: operation.inputs ?? [],
        };
      }),
    );
    setProgress({});
    setInputBindings({});
    setResult(null);
  };

  const run = async () => {
    if (!steps.length || !targets.length || running) return;
    const usedInputNames = recipeInputNames(steps);
    const activeBindings = Object.fromEntries(
      Object.entries(inputBindings).filter(([name]) => usedInputNames.has(name)),
    );
    const validationErrors = recipeErrors(steps, activeBindings);
    if (validationErrors.length) {
      setSchemaError(validationErrors.join(" · "));
      return;
    }
    setSchemaError("");
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
        // region_ref is carried, not destructured away: a preset that
        // names a region runs scoped under a folder watch and would run
        // WHOLE-IMAGE here, with no error, if it were dropped.
        steps.map(({ op, params, inputs, region_ref }) => ({
          op,
          params,
          ...(region_ref ? { region_ref } : {}),
          ...(inputs
            ? { inputs: Object.fromEntries(Object.entries(inputs).filter(
                ([, ref]) => {
                  const value = activeBindings[ref];
                  return Array.isArray(value) ? value.length > 0 : Boolean(value);
                },
              )) }
            : {}),
        })),
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
        activeBindings,
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
      params: {
        version: result.version,
        steps: result.steps,
        inputs: result.inputs ?? {},
      },
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
        steps={steps.map(({ op, params, inputs, region_ref }) => ({
          op, params, inputs, ...(region_ref ? { region_ref } : {}),
        }))}
        disabled={running || operations.length === 0}
        onLoad={loadPreset}
      />

      <MacroBridge
        steps={steps.map(({ op, params, inputs, region_ref }) => ({
          op, params, inputs, ...(region_ref ? { region_ref } : {}),
        }))}
        inputBindings={inputBindings}
        disabled={running || operations.length === 0}
        onLoad={(macroSteps) =>
          loadPreset({
            version: 2, id: "macro", name: "Recorded macro",
            steps: macroSteps, createdAt: "", updatedAt: "",
          })
        }
      />

      <WatchFolderSection
        onDerived={ingestDerived}
        operations={operations}
        images={images}
        order={order}
      />

      {schemaError && <div className="fvd-batch-empty">{schemaError}</div>}
      <input
        className="fvd-batch-search"
        type="search"
        aria-label="Find an operation"
        placeholder={`Find among ${operations.length} operations…`}
        value={operationSearch}
        disabled={running}
        onChange={(event) => setOperationSearch(event.target.value)}
      />
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
                onClick={() => setSteps((current) => {
                  const next = current.filter((candidate) => candidate.uid !== step.uid);
                  const retained = recipeInputNames(next);
                  setInputBindings((bindings) => Object.fromEntries(
                    Object.entries(bindings).filter(([name]) => retained.has(name)),
                  ));
                  return next;
                })}
                title="Remove step"
              >
                ×
              </button>
            </div>
          ))
        )}
      </div>

      {recipeInputNames(steps).size > 0 && (
        <RecipeInputs
          steps={steps}
          images={images}
          order={order}
          bindings={inputBindings}
          disabled={running}
          onChange={setInputBindings}
        />
      )}

      {steps.length > 0 && (
        <div className="fvd-batch-summary" aria-label="Run summary">
          <strong>Ready to run:</strong> {targets.length} input image
          {targets.length === 1 ? "" : "s"} × {steps.length} step
          {steps.length === 1 ? "" : "s"} = {targets.length * steps.length} operations
          {recipeInputNames(steps).size
            ? ` · ${recipeInputNames(steps).size} named recipe input${recipeInputNames(steps).size === 1 ? "" : "s"}`
            : ""}
        </div>
      )}

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
                  {error && <span className="err">Error: {error}</span>}
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
