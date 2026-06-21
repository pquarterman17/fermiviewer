// Colormap LUTs for the WebGL display shader. Stored as sparse control
// stops, interpolated to 256 RGBA entries at upload time. Viridis /
// inferno stops sampled from the matplotlib reference tables.

export type ColormapName =
  | "gray"
  | "invert"
  | "viridis"
  | "inferno"
  | "fire"
  | "ice"
  | "redblue"
  | "label"
  | "custom";

// "label" is intentionally NOT offered as a manual pick — it is auto-applied
// to grain/label maps (it needs the per-image label count) via buildLabelLut.
export const COLORMAP_NAMES: ColormapName[] = [
  "gray",
  "invert",
  "viridis",
  "inferno",
  "fire",
  "ice",
  "redblue",
  "custom",
];

type Stop = [number, number, number]; // rgb 0–255, evenly spaced in t

const STOPS: Record<ColormapName, Stop[]> = {
  gray: [
    [0, 0, 0],
    [255, 255, 255],
  ],
  invert: [
    [255, 255, 255],
    [0, 0, 0],
  ],
  viridis: [
    [68, 1, 84],
    [72, 40, 120],
    [62, 74, 137],
    [49, 104, 142],
    [38, 130, 142],
    [31, 158, 137],
    [53, 183, 121],
    [109, 205, 89],
    [180, 222, 44],
    [253, 231, 37],
  ],
  inferno: [
    [0, 0, 4],
    [27, 12, 65],
    [74, 12, 107],
    [120, 28, 109],
    [165, 44, 96],
    [207, 68, 70],
    [237, 105, 37],
    [251, 155, 6],
    [247, 209, 61],
    [252, 255, 164],
  ],
  // classic EM "hot" ramp
  fire: [
    [0, 0, 0],
    [120, 0, 0],
    [230, 60, 0],
    [255, 150, 0],
    [255, 230, 100],
    [255, 255, 255],
  ],
  ice: [
    [0, 0, 0],
    [0, 40, 110],
    [0, 110, 190],
    [60, 180, 230],
    [180, 235, 255],
    [255, 255, 255],
  ],
  // diverging blue-white-red (strain / difference maps)
  redblue: [
    [25, 60, 180],
    [120, 160, 230],
    [245, 245, 245],
    [230, 120, 100],
    [180, 25, 35],
  ],
  custom: [
    [0, 0, 0],
    [255, 255, 255],
  ], // placeholder — resolved from localStorage at build time
  label: [
    [0, 0, 0],
    [255, 255, 255],
  ], // placeholder — buildLut short-circuits "label" to buildLabelLut
};

function hexToStop(h: string): Stop | null {
  const c = h.replace("#", "").trim();
  const v =
    c.length === 3
      ? c.split("").map((x) => parseInt(x + x, 16))
      : c.length === 6
        ? [c.slice(0, 2), c.slice(2, 4), c.slice(4, 6)].map((x) =>
            parseInt(x, 16),
          )
        : null;
  return v && v.every((n) => Number.isFinite(n)) ? (v as Stop) : null;
}

/** Parse "#000, #a070f0, #fff" → stops; store for the custom cmap.
 *  Returns false (and stores nothing) when fewer than 2 stops parse. */
export function setCustomColormap(spec: string): boolean {
  const stops = spec
    .split(",")
    .map((s) => hexToStop(s))
    .filter((s): s is Stop => s !== null);
  if (stops.length < 2) return false;
  localStorage.setItem("fv_custom_cmap", JSON.stringify(stops));
  return true;
}

function customStops(): Stop[] {
  try {
    const stops = JSON.parse(
      localStorage.getItem("fv_custom_cmap") ?? "[]",
    ) as Stop[];
    return stops.length >= 2 ? stops : STOPS.gray;
  } catch {
    return STOPS.gray;
  }
}

/** HSV (h 0–360, s/v 0–1) → rgb 0–255. */
function hsvToRgb(h: number, s: number, v: number): Stop {
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  const [r, g, b] =
    h < 60
      ? [c, x, 0]
      : h < 120
        ? [x, c, 0]
        : h < 180
          ? [0, c, x]
          : h < 240
            ? [0, x, c]
            : h < 300
              ? [x, 0, c]
              : [c, 0, x];
  return [
    Math.round((r + m) * 255),
    Math.round((g + m) * 255),
    Math.round((b + m) * 255),
  ];
}

/** Distinct flat colour for an integer label id (0 = black background/grain
 *  boundary; ≥1 = golden-angle-spaced hue so adjacent ids differ maximally). */
export function labelColor(k: number): Stop {
  if (k <= 0) return [0, 0, 0];
  const hue = ((k - 1) * 137.508) % 360; // golden angle → max separation
  const val = 0.78 + 0.2 * (((k - 1) % 3) / 2); // nudge value so cycles differ
  return hsvToRgb(hue, 0.7, val);
}

/** 256×RGBA8 LUT of FLAT colour bands, one per integer label id, for grain/
 *  label maps (raster values are integer ids in 0..nLabels-1). LUT index i
 *  maps back to label k = round(t·maxLabel), so each id lands on its band. */
export function buildLabelLut(nLabels: number): Uint8Array {
  const maxLabel = Math.max(1, Math.floor(nLabels) - 1);
  const out = new Uint8Array(256 * 4);
  for (let i = 0; i < 256; i++) {
    const [r, g, b] = labelColor(Math.round((i / 255) * maxLabel));
    out[i * 4] = r;
    out[i * 4 + 1] = g;
    out[i * 4 + 2] = b;
    out[i * 4 + 3] = 255;
  }
  return out;
}

/** 256×1 RGBA8 LUT for upload as a texture. */
export function buildLut(name: ColormapName): Uint8Array {
  // "label" needs the per-image count; this generic path uses a default cycle
  // (used by code that calls buildLut(display.cmap) without the label count)
  if (name === "label") return buildLabelLut(24);
  const stops = name === "custom" ? customStops() : STOPS[name];
  const out = new Uint8Array(256 * 4);
  const n = stops.length - 1;
  for (let i = 0; i < 256; i++) {
    const t = (i / 255) * n;
    const k = Math.min(n - 1, Math.floor(t));
    const f = t - k;
    for (let c = 0; c < 3; c++) {
      out[i * 4 + c] = Math.round(stops[k][c] * (1 - f) + stops[k + 1][c] * f);
    }
    out[i * 4 + 3] = 255;
  }
  return out;
}
