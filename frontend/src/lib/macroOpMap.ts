// Wire-call → server-op translation table (Scripting #8: macro convergence).
//
// The macro recorder captures the same POST bodies routes/filter.py,
// routes/analysis.py and routes/eds_quant.py already accept. This module
// knows which of those wire calls have an equivalent step in the batch op
// vocabulary (ops/catalogue.py + ops/catalogue_spectral.py) and how to
// translate the wire body into that op's params — same rule the ops
// catalogues themselves follow: no reimplemented logic, just a field-shape
// translation to the SAME op names/params the server already validates.
//
// Param-format notes (mirrors ops/catalogue_spectral.py's own docstring):
// list params become comma-separated strings ("Fe,O"), window pairs become
// comma-separated "lo:hi" pairs ("708:758,532:582"). A wire call whose shape
// doesn't match the recorder's deliberately smaller translation table
// returns null so the caller can keep it as a legacy step instead of
// dropping it. This is not the operation-coverage inventory: many routes
// are op-backed but have not yet been given a lossless wire-body mapping.

export interface OpStep {
  op: string;
  params: Record<string, unknown>;
}

// Names registered as image/geometry ops in ops/catalogue.py that /api/filter
// also accepts verbatim as a `kind` — the only /api/filter kinds with a
// direct op equivalent ("crop" and "rotate" have none).
const FILTER_OP_NAMES = new Set([
  "gaussian", "median", "unsharp", "butterworth", "clahe", "bin",
  "plane_level", "morph", "multiotsu",
  "rotate90", "rotate180", "rotate270", "fliph", "flipv",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isTuple2(value: unknown): value is [number, number] {
  return Array.isArray(value) && value.length === 2 &&
    isFiniteNumber(value[0]) && isFiniteNumber(value[1]);
}

function csv(values: unknown[]): string {
  return values.join(",");
}

function windowsCsv(windows: [number, number][]): string {
  return windows.map(([lo, hi]) => `${lo}:${hi}`).join(",");
}

function mapFilter(body: Record<string, unknown>): OpStep | null {
  const kind = body["kind"];
  if (typeof kind !== "string" || !FILTER_OP_NAMES.has(kind)) return null;
  const params = body["params"];
  return { op: kind, params: isRecord(params) ? { ...params } : {} };
}

function mapEelsMap(body: Record<string, unknown>): OpStep | null {
  const signal = body["signal_window"];
  if (!isTuple2(signal)) return null;
  const params: Record<string, unknown> = {
    signal_lo: signal[0],
    signal_hi: signal[1],
    method: typeof body["method"] === "string" ? body["method"] : "powerlaw",
  };
  const bg = body["background_window"];
  if (isTuple2(bg)) {
    params.bg_lo = bg[0];
    params.bg_hi = bg[1];
  }
  return { op: "eels_map", params };
}

interface WireEdge {
  element: string;
  shell: string;
  z: number;
  onset_ev: number;
  signal_window: [number, number];
  bg_window: [number, number];
}

function isWireEdge(value: unknown): value is WireEdge {
  if (!isRecord(value)) return false;
  return (
    typeof value.element === "string" &&
    typeof value.shell === "string" &&
    isFiniteNumber(value.z) &&
    isFiniteNumber(value.onset_ev) &&
    isTuple2(value.signal_window) &&
    isTuple2(value.bg_window)
  );
}

function mapEelsQuantify(body: Record<string, unknown>): OpStep | null {
  const edges = body["edges"];
  if (!Array.isArray(edges) || edges.length === 0 || !edges.every(isWireEdge)) {
    return null;
  }
  const typed = edges as WireEdge[];
  return {
    op: "eels_quantify",
    params: {
      elements: csv(typed.map((e) => e.element)),
      shells: csv(typed.map((e) => e.shell)),
      z: csv(typed.map((e) => e.z)),
      onset_ev: csv(typed.map((e) => e.onset_ev)),
      signal_windows: windowsCsv(typed.map((e) => e.signal_window)),
      bg_windows: windowsCsv(typed.map((e) => e.bg_window)),
      e0_kv: isFiniteNumber(body["e0_kv"]) ? body["e0_kv"] : 200,
      beta_mrad: isFiniteNumber(body["beta_mrad"]) ? body["beta_mrad"] : 10,
      method: typeof body["method"] === "string" ? body["method"] : "powerlaw",
    },
  };
}

function mapEdsQuantify(body: Record<string, unknown>): OpStep | null {
  const elements = body["elements"];
  if (
    !Array.isArray(elements) || elements.length === 0 ||
    !elements.every((e) => typeof e === "string")
  ) {
    return null;
  }
  return {
    op: "eds_quantify",
    params: {
      elements: csv(elements),
      method: typeof body["method"] === "string" ? body["method"] : "cliff-lorimer",
      thickness_nm: isFiniteNumber(body["thickness_nm"]) ? body["thickness_nm"] : 100,
      take_off_angle_deg:
        isFiniteNumber(body["take_off_angle_deg"]) ? body["take_off_angle_deg"] : 20,
    },
  };
}

/** Translate one recorded wire call to its op-vocabulary equivalent, or
 *  null when the endpoint (or this particular body shape) has none. */
export function wireToOp(path: string, body: Record<string, unknown>): OpStep | null {
  if (path === "/api/filter") return mapFilter(body);
  if (path === "/api/eels/map") return mapEelsMap(body);
  if (path === "/api/eels/quantify") return mapEelsQuantify(body);
  if (path === "/api/eds/quantify") return mapEdsQuantify(body);
  return null;
}
