// Analysis ▸ AFM / SPM: one home for scanning-probe work. Levelling runs
// the same POST /filter kinds as the Tools panel's "Level & Correct" group
// (calc/afm_level.py); the rest reuses the existing workshops — roughness,
// 3-D surface, particles/grains on the height map — rather than duplicating
// them for AFM.
import { toAnalysisRoi, type AnalysisRoi } from "../../../hooks/useAnalysisRoi";
import { afmMap, afmStepHeight, applyFilter, openAfmChannels } from "../../../lib/api";
import { coerceParams } from "../../../lib/params";
import { runTransform } from "../../../lib/transforms";
import { TRANSFORM_TOOLS } from "../../../lib/transformTools";
import { askParams } from "../../../store/params";
import { openStructureWorkshop } from "../../../store/workshopNavigation";
import type { Entry, MenuCtx } from "./menuTypes";

/** The pixel (row, col) containing a normalized 0–1 point, clamped to
 *  [0, n-1]: a point stored on the far edge (x or y === 1 — pointer capture
 *  and vertex drags clamp to [0, 1]) is the last pixel, not one past it. */
export function pixelIndex(t: number, n: number): number {
  return Math.min(n - 1, Math.max(0, Math.floor(t * n)));
}

/** Three normalized measure points → [row, col] pixel indices. */
export function threePointPixels(
  pts: { x: number; y: number }[],
  shape: number[],
): [number, number][] {
  const [h, w] = shape;
  return pts.map((p) => [pixelIndex(p.y, h), pixelIndex(p.x, w)]);
}

/** Ask for a Level & Correct tool's params, then run it. */
async function levelWith(kind: string): Promise<void> {
  const tool = TRANSFORM_TOOLS.find((t) => t.kind === kind);
  if (!tool) return;
  const fields = tool.fields ?? [];
  const v = fields.length ? await askParams(tool.label, fields) : {};
  if (v) runTransform(tool, coerceParams(v, fields));
}

export function buildAfmMenu(ctx: MenuCtx): Entry {
  const { store } = ctx;
  const id = store.activeId;
  const noImage = !id;

  // Three-point levelling takes its points from the active image's most
  // recent angle measure (3 clicks) or 3-vertex polygon.
  const threePoints = (): [number, number][] | null => {
    if (!id) return null;
    const meta = store.images[id];
    const m = (store.measures[id] ?? [])
      .filter((x) => (x.kind === "angle" || x.kind === "polygon") && x.pts.length === 3)
      .at(-1);
    if (!meta || !m) return null;
    return threePointPixels(m.pts, meta.shape);
  };

  // Step height and the PSD/ACF maps use the active image's most recent
  // rectangle (or ellipse box) ROI; the maps fall back to the whole image.
  const lastRoi = (): AnalysisRoi | null => {
    if (!id) return null;
    const meta = store.images[id];
    const m = (store.measures[id] ?? []).filter((x) => x.kind === "roi" || x.kind === "ellipse").at(-1);
    return meta && m ? toAnalysisRoi(m, meta.shape) : null;
  };
  const surfaceMap = (kind: "psd" | "acf") => {
    if (!id) return;
    const what = kind === "psd" ? "2-D PSD" : "autocorrelation";
    store.setStatus(`${what}…`);
    afmMap(id, kind, { roi: lastRoi() })
      .then((m) => {
        store.ingestDerived([m]);
        store.setStatus(`${what} → ${m.name}`);
      })
      .catch((e: Error) => store.setStatus(`${what}: ${e.message}`));
  };

  return {
    label: "AFM / SPM",
    submenu: [
      { label: "Plane Level…", disabled: noImage, action: () => void levelWith("plane_level") },
      { label: "Level Rows…", disabled: noImage, action: () => void levelWith("row_level") },
      { label: "Remove Scars…", disabled: noImage, action: () => void levelWith("scar_removal") },
      {
        label: "Three-Point Level (last angle / triangle)",
        disabled: noImage || threePoints() === null,
        action: () => {
          const pts = threePoints();
          if (!id || !pts) return;
          store.setStatus("three-point level…");
          applyFilter(id, "three_point_level", { points: pts })
            .then((m) => {
              store.ingestDerived([m]);
              store.setStatus(`three-point level → ${m.name}`);
            })
            .catch((e: Error) => store.setStatus(`three-point level: ${e.message}`));
        },
      },
      { label: "Fix Zero…", disabled: noImage, action: () => void levelWith("zero_level") },
      { kind: "sep" },
      {
        label: "Open Other Channels",
        disabled: noImage,
        action: () => {
          if (!id) return;
          openAfmChannels(id)
            .then((metas) => {
              if (metas.length) store.ingestDerived(metas);
              store.setStatus(
                metas.length
                  ? `opened ${metas.length} channel${metas.length === 1 ? "" : "s"}`
                  : "all channels of this scan are already open",
              );
            })
            .catch((e: Error) => store.setStatus(`channels: ${e.message}`));
        },
      },
      { kind: "sep" },
      {
        label: "Surface Analysis (ISO 25178)…",
        disabled: noImage,
        action: () => store.openTool("afmsurface"),
      },
      { label: "2-D Power Spectrum Map", disabled: noImage, action: () => surfaceMap("psd") },
      { label: "Autocorrelation Map", disabled: noImage, action: () => surfaceMap("acf") },
      {
        label: "Step Height (last ROI across the step)",
        disabled: noImage || lastRoi() === null,
        action: () => {
          const roi = lastRoi();
          if (!id || !roi) return;
          afmStepHeight(id, roi)
            .then((r) =>
              store.setStatus(
                `step height ${r.height.toPrecision(4)} ${r.unit} ` +
                  `(terrace rms ${r.lower_std.toPrecision(2)} / ${r.upper_std.toPrecision(2)} ${r.unit})`,
              ),
            )
            .catch((e: Error) => store.setStatus(`step height: ${e.message}`));
        },
      },
      { kind: "sep" },
      { label: "Surface Roughness", disabled: noImage, action: () => store.openTool("roughness") },
      { label: "3-D Surface", disabled: noImage, action: () => store.openTool("surface") },
      { label: "Particles…", disabled: noImage, action: () => openStructureWorkshop("Particles") },
      { label: "Grains…", disabled: noImage, action: () => openStructureWorkshop("Grains") },
    ],
  };
}
