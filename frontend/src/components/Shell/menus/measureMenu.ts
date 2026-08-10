// Measure menu builder, split out of MenuBar.tsx (repo-health #33). Entries
// moved verbatim; only `store`/helper references now come from ctx.
import type { Entry, MenuCtx } from "./menuTypes";

export function buildMeasureMenu(ctx: MenuCtx): Entry[] {
  const { store, calibrateFromMeasurement } = ctx;
  return [
    { kind: "section", label: "Tools" },
    {
      label: "Distance",
      shortcut: "D",
      disabled: !store.activeId,
      action: () => store.setCaptureMode("distance"),
    },
    {
      label: "Angle",
      shortcut: "G",
      disabled: !store.activeId,
      action: () => store.setCaptureMode("angle"),
    },
    {
      label: "Line Profile",
      shortcut: "L",
      disabled: !store.activeId,
      action: () => store.setCaptureMode("profile"),
    },
    {
      label: "Box Profile",
      shortcut: "B",
      disabled: !store.activeId,
      action: () => store.setCaptureMode("box-profile"),
    },
    {
      label: "ROI Statistics",
      shortcut: "R",
      disabled: !store.activeId,
      action: () => store.setCaptureMode("roi"),
    },
    {
      label: "Polyline",
      shortcut: "P",
      disabled: !store.activeId,
      action: () => store.setCaptureMode("polyline"),
    },
    {
      label: "Polygon",
      disabled: !store.activeId,
      action: () => store.setCaptureMode("polygon"),
    },
    {
      label: "Lasso",
      disabled: !store.activeId,
      action: () => store.setCaptureMode("lasso"),
    },
    { kind: "section", label: "Calibration" },
    {
      label: "Calibrate from Measurement…",
      disabled:
        !store.activeId ||
        !(store.measures[store.activeId ?? ""] ?? []).some(
          (m) => m.kind === "distance",
        ),
      action: () => calibrateFromMeasurement(),
    },
    { kind: "sep" },
    {
      label: "Clear Measurements",
      disabled: !store.activeId,
      action: () => {
        const id = store.activeId;
        if (id) store.clearMeasures(id, null);
      },
    },
  ];
}
