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
  | "custom";

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

/** 256×1 RGBA8 LUT for upload as a texture. */
export function buildLut(name: ColormapName): Uint8Array {
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
