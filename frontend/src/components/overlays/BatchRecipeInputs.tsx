import type {
  BatchInputBindings,
  BatchInputSchema,
  BatchOperation,
  BatchRecipeStep,
  ImageMeta,
} from "../../lib/api";
import type { ParamField } from "../../lib/params";

export interface RecipeStep extends BatchRecipeStep {
  uid: number;
  label: string;
  produces: BatchOperation["produces"];
  inputSchemas: BatchInputSchema[];
}

export function paramFields(operation: BatchOperation): ParamField[] {
  return operation.params.map((param) => {
    const fallback = param.shape
      ? []
      : param.default ?? (param.type === "bool" ? false : param.type === "str" ? "" : 0);
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
      type: param.shape
        ? "text"
        : param.type === "bool"
          ? "boolean"
          : param.type === "str"
            ? "text"
            : "number",
      default: (param.shape ? JSON.stringify(fallback) : fallback) as number | string | boolean,
      hint: [
        param.doc,
        param.shape ? "JSON list" : "",
        param.minimum != null ? `min ${param.minimum}` : "",
        param.maximum != null ? `max ${param.maximum}` : "",
      ].filter(Boolean).join(" · "),
    };
  });
}

export function parsedParams(
  operation: BatchOperation,
  values: Record<string, unknown>,
): Record<string, unknown> {
  const result = { ...values };
  for (const schema of operation.params) {
    if (!schema.shape || typeof result[schema.name] !== "string") continue;
    try {
      const parsed: unknown = JSON.parse(result[schema.name] as string);
      if (!Array.isArray(parsed)) throw new Error();
      result[schema.name] = parsed;
    } catch {
      throw new Error(`${schema.name.replaceAll("_", " ")} must be a JSON list`);
    }
  }
  return result;
}

export function recipeInputNames(steps: RecipeStep[]): Set<string> {
  return new Set(steps.flatMap((step) => Object.values(step.inputs ?? {})));
}

export function allocateInputReferences(
  schemas: BatchInputSchema[],
  used: Set<string>,
  existing: Record<string, string> = {},
): Record<string, string> {
  const inputs = { ...existing };
  Object.values(existing).forEach((reference) => used.add(reference));
  for (const schema of schemas) {
    if (inputs[schema.name]) continue;
    let reference = schema.name;
    let suffix = 2;
    while (used.has(reference)) reference = `${schema.name}_${suffix++}`;
    used.add(reference);
    inputs[schema.name] = reference;
  }
  return inputs;
}

export function recipeErrors(
  steps: RecipeStep[],
  bindings: BatchInputBindings,
): string[] {
  const errors: string[] = [];
  steps.forEach((step, index) => {
    for (const schema of step.inputSchemas) {
      const ref = step.inputs?.[schema.name];
      const binding = ref ? bindings[ref] : undefined;
      const count = Array.isArray(binding) ? binding.length : binding ? 1 : 0;
      const minimum = schema.variadic ? (schema.min_count ?? (schema.required ? 1 : 0)) : 1;
      if ((schema.required || count > 0) && count < minimum) {
        errors.push(`Step ${index + 1} needs ${schema.doc || schema.name}`);
      }
      if (schema.max_count != null && count > schema.max_count) {
        errors.push(`Step ${index + 1} allows at most ${schema.max_count} ${schema.name} images`);
      }
    }
  });
  return errors;
}

export default function RecipeInputs({
  steps, images, order, bindings, disabled, onChange,
}: {
  steps: RecipeStep[];
  images: Record<string, ImageMeta>;
  order: string[];
  bindings: BatchInputBindings;
  disabled: boolean;
  onChange: (next: BatchInputBindings) => void;
}) {
  const entries = steps.flatMap((step, stepIndex) =>
    step.inputSchemas.map((schema) => ({
      schema,
      stepIndex,
      reference: step.inputs?.[schema.name] ?? schema.name,
    })),
  );
  return (
    <section className="fvd-batch-inputs" aria-label="Recipe inputs">
      <div className="fvd-batch-preset-head">
        <span>Recipe inputs</span>
        <span className="fvd-ws-note">Choose open images for portable named references</span>
      </div>
      {entries.map(({ schema, stepIndex, reference }) => {
        const value = bindings[reference];
        return (
          <label key={`${stepIndex}:${schema.name}`} className="fvd-batch-input-row">
            <span>
              Step {stepIndex + 1} · {schema.name.replaceAll("_", " ")}
              {schema.required ? " *" : ""}
            </span>
            <select
              aria-label={`Step ${stepIndex + 1} ${schema.name} input`}
              multiple={schema.variadic}
              value={schema.variadic ? (Array.isArray(value) ? value : []) : (typeof value === "string" ? value : "")}
              disabled={disabled}
              onChange={(event) => onChange({
                ...bindings,
                [reference]: schema.variadic
                  ? Array.from(event.currentTarget.selectedOptions, (option) => option.value)
                  : event.currentTarget.value,
              })}
              title={schema.doc}
            >
              {!schema.variadic && <option value="">Choose an image…</option>}
              {order.map((id) => <option key={id} value={id}>{images[id]?.name ?? id}</option>)}
            </select>
            <code>{reference}</code>
            {schema.variadic && (
              <small className="fvd-ws-note">Uses the open-image order shown here.</small>
            )}
          </label>
        );
      })}
    </section>
  );
}
