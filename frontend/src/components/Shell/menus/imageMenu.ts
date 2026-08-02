// Image menu builder, split out of MenuBar.tsx (repo-health #33). Entries
// moved verbatim; only `store`/helper references now come from ctx.
import {
  analyzeAlignStack,
  analyzeImageMath,
  analyzeMip,
  analyzeMontage,
  analyzeVdf,
  applyCalibration,
  detectScaleBar,
  explodeStack,
  imageFft,
} from "../../../lib/api";
import { loadMacro, replayMacro, startRecording, stopRecording } from "../../../lib/macro";
import { applyGeometry, cropToRoi } from "../../../lib/stageOps";
import { askParams } from "../../../store/params";
import { useViewer } from "../../../store/viewer";
import type { Entry, MenuCtx } from "./menuTypes";
import { num } from "./menuTypes";

export function buildImageMenu(ctx: MenuCtx): Entry[] {
  const {
    store,
    macroRec,
    setMacroRec,
    derived,
    runBatchCrop,
    runBatch,
    radialDock,
    calibrateFromMeasurement,
  } = ctx;
  return [
    { label: "Transform", submenu: [
    {
      label: "Rotate 90° CW",
      disabled: !store.activeId,
      action: () => applyGeometry("rotate90"),
    },
    {
      label: "Rotate 90° CCW",
      disabled: !store.activeId,
      action: () => applyGeometry("rotate270"),
    },
    {
      label: "Rotate 180°",
      disabled: !store.activeId,
      action: () => applyGeometry("rotate180"),
    },
    {
      label: "Flip Horizontal",
      disabled: !store.activeId,
      action: () => applyGeometry("fliph"),
    },
    {
      label: "Flip Vertical",
      disabled: !store.activeId,
      action: () => applyGeometry("flipv"),
    },
    {
      label: "Crop to ROI",
      disabled: !store.activeId,
      action: () => cropToRoi(),
    },
    ] },
    { label: "Combine & Stack", submenu: [
    {
      label: "Image Math…",
      disabled: !store.activeId || store.order.length < 2,
      action: () => {
        void (async () => {
          const a = store.activeId;
          if (!a) return;
          const others = store.order.filter((i) => i !== a);
          const v = await askParams("Image Math (A = active)", [
            {
              key: "b",
              label: "Image B",
              type: "select",
              default: store.images[others[0]]?.name ?? "",
              options: others.map((i) => store.images[i]?.name ?? i),
            },
            {
              key: "op",
              label: "Operation",
              type: "select",
              default: "subtract",
              options: ["subtract", "divide", "ratio", "add"],
            },
          ]);
          if (!v) return;
          const bId = others.find(
            (i) => (store.images[i]?.name ?? i) === v["b"],
          );
          if (!bId) return;
          analyzeImageMath(
            a,
            bId,
            v["op"] as "subtract" | "divide" | "ratio" | "add",
          )
            .then((r) => store.ingestDerived([r.image]))
            .catch((e: Error) => store.setStatus(`math: ${e.message}`));
        })();
      },
    },
    {
      label: "Stack → Frames",
      disabled:
        !store.activeId ||
        store.images[store.activeId ?? ""]?.kind !== "spectrum_image",
      action: () => {
        const id = store.activeId;
        if (!id) return;
        store.setStatus("exploding stack…");
        explodeStack(id)
          .then((metas) => {
            store.ingestDerived(metas);
            store.setStatus(
              `stack exploded: ${metas.length} frames — use [ ] to ` +
                "navigate, Align Stack / MIP / GIF to process",
            );
          })
          .catch((e: Error) => store.setStatus(`explode: ${e.message}`));
      },
    },
    {
      label: `Align Stack (${store.selected.length} selected)`,
      disabled: store.selected.length < 2,
      action: () => {
        analyzeAlignStack(store.selected)
          .then((r) => {
            store.ingestDerived(r.images);
            const mx = Math.max(
              ...r.shifts.flat().map((v) => Math.abs(v)),
            );
            store.setStatus(
              `aligned ${r.images.length} images · max shift ${mx} px`,
            );
          })
          .catch((e: Error) => store.setStatus(`align: ${e.message}`));
      },
    },
    {
      label: "Maximum Intensity Projection",
      disabled: store.selected.length < 2,
      action: () => {
        analyzeMip(store.selected)
          .then((r) => store.ingestDerived([r.image]))
          .catch((e: Error) => store.setStatus(`mip: ${e.message}`));
      },
    },
    {
      label: `Montage (${store.selected.length} selected)…`,
      disabled: store.selected.length < 1,
      action: () => {
        void (async () => {
          const n = store.selected.length;
          const v = await askParams("Montage", [
            num("cols", "Columns (0 = auto)", 0,
                "0 → ceil(√n); frames go left-to-right, top-to-bottom"),
            num("gap", "Gap (px)", 4, "Inter-tile gap in pixels"),
            num("font_size", "Label font (px)", 14,
                "0 to disable labels"),
          ]);
          if (!v) return;
          const cols = Math.round(v.cols as number);
          const gap = Math.max(0, Math.round(v.gap as number));
          const font_size = Math.max(0, Math.round(v.font_size as number));
          store.setStatus("building montage…");
          analyzeMontage(store.selected, {
            cols: cols > 0 ? cols : null,
            labels: font_size > 0,
            gap,
            font_size: font_size > 0 ? font_size : 14,
          })
            .then((r) => {
              store.ingestDerived([r.image]);
              store.setStatus(
                `montage: ${n} tiles → ${r.image.shape[1]}×${r.image.shape[0]} px`,
              );
            })
            .catch((e: Error) => store.setStatus(`montage: ${e.message}`));
        })();
      },
    },
    {
      label: `Batch Crop to ROI (${store.selected.length})`,
      disabled: !store.activeId || store.selected.length < 2,
      action: () => void runBatchCrop(),
    },
    ] },
    { label: "Fourier", submenu: [
    {
      label: "FFT",
      disabled: !store.activeId,
      action: () => derived("FFT", (id) => imageFft(id).then((m) => [m])),
    },
    {
      label: "Virtual Dark Field…",
      disabled: !store.activeId,
      action: () => {
        void (async () => {
          const meta = store.activeId
            ? store.images[store.activeId]
            : undefined;
          const h = meta?.shape[0] ?? 0;
          const w = meta?.shape[1] ?? 0;
          const v = await askParams("Virtual Dark Field", [
            num("row", "Centre row (FFT px)", Math.round(h / 2)),
            num("col", "Centre col (FFT px)", Math.round(w / 2)),
            num("radius", "Mask radius (px)", 10),
          ]);
          if (!v) return;
          derived("VDF", (id) =>
            analyzeVdf(
              id,
              [v["row"] as number, v["col"] as number],
              v["radius"] as number,
            ).then((r) => [r.image]),
          );
        })();
      },
    },
    ] },
    { label: "Batch & Macro", submenu: [
    {
      label: "Batch Recipe…",
      disabled: store.order.length === 0,
      action: () => store.setBatchOpen(true),
    },
    {
      label: "Batch Apply (single op)…",
      disabled: store.order.length === 0,
      action: () => void runBatch(),
    },
    {
      label: macroRec ? "Stop Macro Recording" : "Record Macro",
      action: () => {
        if (macroRec) {
          const { total, legacy } = stopRecording();
          setMacroRec(false);
          store.setStatus(
            `macro saved: ${total} step${total === 1 ? "" : "s"}` +
              (legacy ? ` (${legacy} not batchable)` : ""),
          );
        } else {
          startRecording();
          setMacroRec(true);
          store.setStatus(
            "recording macro — run Image/Analyze ops, then stop",
          );
        }
      },
    },
    {
      label: "Replay Macro",
      disabled: !store.activeId || loadMacro().length === 0 || macroRec,
      action: () => {
        const id = store.activeId;
        if (!id) return;
        store.setStatus("replaying macro…");
        replayMacro(id, (m) => store.ingestDerived([m]))
          .then((n) => store.setStatus(`macro replayed: ${n} steps`))
          .catch((e: Error) => store.setStatus(`macro: ${e.message}`));
      },
    },
    ] },
    { label: "Calibration", submenu: [
    {
      label: "Calibrate Pixel Size…",
      disabled: !store.activeId,
      action: () => {
        void (async () => {
          const v = await askParams("Calibrate Pixel Size", [
            num("px", "Pixel size", 1),
            {
              key: "unit",
              label: "Unit",
              type: "select",
              default: "nm",
              options: ["nm", "µm", "Å", "pm", "mm"],
            },
            {
              key: "save",
              label: "Save to calibration DB",
              type: "boolean",
              default: false,
            },
          ]);
          const id = store.activeId;
          if (!v || !id) return;
          let saveKey: string | undefined;
          if (v["save"]) {
            saveKey =
              window.prompt(
                "Calibration key (instrument|mag):",
                "scope|mag",
              ) ?? undefined;
          }
          applyCalibration(
            id,
            v["px"] as number,
            v["unit"] as string,
            saveKey,
          )
            .then((r) => {
              useViewer.setState((s) => ({
                images: { ...s.images, [r.image.id]: r.image },
              }));
              store.setStatus(
                `calibrated: ${r.image.pixel_size} ${r.image.pixel_unit}/px`,
              );
            })
            .catch((e: Error) => store.setStatus(e.message));
        })();
      },
    },
    {
      label: "Manage Calibrations…",
      action: () => store.setCalibOpen(true),
    },
    {
      label: "Auto-detect Scale Bar…",
      disabled: !store.activeId,
      action: () => {
        void (async () => {
          const id = store.activeId;
          if (!id) return;
          const det = await detectScaleBar(id).catch((e: Error) => {
            store.setStatus(`detect: ${e.message}`);
            return null;
          });
          if (!det) return;
          if (!det.found) {
            store.setStatus(det.msg);
            return;
          }
          const v = await askParams(
            `Scale bar found: ${det.bar_len} px — physical length?`,
            [
              num("len", "Bar length", 100),
              {
                key: "unit",
                label: "Unit",
                type: "select",
                default: "nm",
                options: ["nm", "µm", "Å", "pm", "mm"],
              },
            ],
          );
          if (!v) return;
          applyCalibration(
            id,
            (v["len"] as number) / det.bar_len,
            v["unit"] as string,
          )
            .then((r) => {
              useViewer.setState((s) => ({
                images: { ...s.images, [r.image.id]: r.image },
              }));
              store.setStatus(
                `calibrated from detected bar: ` +
                  `${r.image.pixel_size?.toPrecision(4)} ` +
                  `${r.image.pixel_unit}/px`,
              );
            })
            .catch((e: Error) => store.setStatus(e.message));
        })();
      },
    },
    {
      label: "Calibrate from Measurement…",
      disabled:
        !store.activeId ||
        !(store.measures[store.activeId ?? ""] ?? []).some(
          (m) => m.kind === "distance",
        ),
      action: () => calibrateFromMeasurement(),
    },
    {
      label: "Edit Metadata…",
      disabled: !store.activeId,
      action: () => store.setMetaOpen(true),
    },
    ] },
    { label: "Profiles", submenu: [
    {
      label: "Radial Profile",
      disabled: !store.activeId,
      action: () => radialDock(false),
    },
    {
      label: "Azimuthal Integration",
      disabled: !store.activeId,
      action: () => radialDock(true),
    },
    ] },
  ];
}
