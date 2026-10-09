// Analysis ▸ AFM / SPM: one home for scanning-probe work. Levelling runs
// the same POST /filter kinds as the Tools panel's "Level & Correct" group
// (calc/afm_level.py); the rest reuses the existing workshops — roughness,
// 3-D surface, particles/grains on the height map — rather than duplicating
// them for AFM.
import { applyFilter, openAfmChannels } from "../../../lib/api";
import { coerceParams } from "../../../lib/params";
import { runTransform } from "../../../lib/transforms";
import { TRANSFORM_TOOLS } from "../../../lib/transformTools";
import { askParams } from "../../../store/params";
import { openStructureWorkshop } from "../../../store/workshopNavigation";
import type { Entry, MenuCtx } from "./menuTypes";

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
    const [h, w] = meta.shape;
    return m.pts.map((p) => [p.y * h - 0.5, p.x * w - 0.5]);
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
      { label: "Surface Roughness", disabled: noImage, action: () => store.openTool("roughness") },
      { label: "3-D Surface", disabled: noImage, action: () => store.openTool("surface") },
      { label: "Particles…", disabled: noImage, action: () => openStructureWorkshop("Particles") },
      { label: "Grains…", disabled: noImage, action: () => openStructureWorkshop("Grains") },
    ],
  };
}
