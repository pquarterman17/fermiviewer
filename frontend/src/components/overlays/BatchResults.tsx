import type { BatchRunResult } from "../../lib/api";
import type { Cell } from "../../lib/resultsExport";

function flatten(
  value: Record<string, unknown>,
  prefix: string,
): Record<string, Cell> {
  const out: Record<string, Cell> = {};
  for (const [key, item] of Object.entries(value)) {
    const column = `${prefix}.${key}`;
    if (item == null || typeof item === "string" || typeof item === "number") {
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

export default function BatchResults({ result }: { result: BatchRunResult }) {
  const table = batchResultTable(result);
  return (
    <div style={{ overflow: "auto", maxHeight: 230 }}>
      <table className="fvd-ws-table">
        <thead>
          <tr>{table.columns.map((column) => <th key={column}>{column}</th>)}</tr>
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
