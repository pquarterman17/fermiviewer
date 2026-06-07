// Inline dropdown menu bar (handoff §4 "Menu bar"). Items run inline;
// WINDOW-badged workshop items arrive with Phase 4 tool windows.

import { useEffect, useRef, useState } from "react";

import {
  analyzeAlignStack,
  analyzeGpa,
  analyzeGrains,
  analyzeGrainsAsync,
  analyzeImageMath,
  analyzeMip,
  analyzeParticles,
  runJob,
  analyzeRadial,
  analyzeRoughness,
  analyzeVdf,
  applyCalibration,
  applyFilter,
  exportBatch,
  exportGif,
  exportImage,
  openRaw,
  renameImage,
  imageFft,
  supportedExtensions,
  type ImageMeta,
} from "../../lib/api";
import {
  isRecording,
  loadMacro,
  replayMacro,
  startRecording,
  stopRecording,
} from "../../lib/macro";
import { applyGeometry, cropToRoi } from "../../lib/stageOps";
import { useStageInfo } from "../../store/stage";
import { DEFAULT_DISPLAY as DD, undoLabel, useViewer } from "../../store/viewer";
import {
  askParams,
  type ParamField,
} from "../overlays/ParamDialog";
import { useResults } from "../overlays/ResultsWindow";

const num = (
  key: string,
  label: string,
  dflt: number,
  hint?: string,
): ParamField => ({ key, label, type: "number", default: dflt, hint });

function recentPaths(): string[] {
  try {
    return (
      JSON.parse(localStorage.getItem("fv_recent") ?? "[]") as string[]
    ).slice(0, 5);
  } catch {
    return [];
  }
}

interface Entry {
  label: string;
  shortcut?: string;
  disabled?: boolean;
  action?: () => void;
}

/** Filter/transform definitions shared by the Image menu and Batch
 *  Apply — one source of truth for kinds + their parameter fields. */
const FILTER_DEFS: { label: string; kind: string; fields?: ParamField[] }[] = [
  { label: "Gaussian Blur…", kind: "gaussian",
    fields: [num("sigma", "Sigma (px)", 2)] },
  { label: "Median Filter…", kind: "median",
    fields: [{ key: "window_size", label: "Window", type: "select",
               default: "3", options: ["3", "5", "7"] }] },
  { label: "Unsharp Mask…", kind: "unsharp",
    fields: [num("sigma", "Sigma (px)", 2), num("amount", "Amount", 1)] },
  { label: "Butterworth…", kind: "butterworth",
    fields: [num("low_cutoff", "Low cutoff (0=off)", 0.05),
             num("high_cutoff", "High cutoff (0–1]", 0.5),
             num("order", "Order", 2)] },
  { label: "CLAHE…", kind: "clahe",
    fields: [num("clip_limit", "Clip limit", 0.01),
             num("num_bins", "Bins", 256)] },
  { label: "Bin…", kind: "bin", fields: [num("bin_size", "Bin size", 2)] },
  { label: "Plane Level", kind: "plane_level" },
  { label: "Rotate 90° CW", kind: "rotate90" },
  { label: "Flip Horizontal", kind: "fliph" },
  { label: "Flip Vertical", kind: "flipv" },
];

export default function MenuBar({
  onFit,
  onActualSize,
}: {
  onFit: () => void;
  onActualSize: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [accept, setAccept] = useState<string>("");
  const [macroRec, setMacroRec] = useState(isRecording());
  const barRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const store = useViewer();

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!barRef.current?.contains(e.target as Node)) setOpen(null);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);

  // accept filter from the backend's parser registry
  useEffect(() => {
    supportedExtensions()
      .then((exts) => setAccept(exts.join(",")))
      .catch(() => undefined);
  }, []);

  // native OS picker → multipart upload
  const openFiles = () => fileRef.current?.click();

  // ⌘O / Ctrl+O opens the picker (a keydown counts as a user gesture)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "o") {
        e.preventDefault();
        fileRef.current?.click();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const onFilesPicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      store.openFiles(files).catch((err: Error) => store.setStatus(err.message));
    }
    e.target.value = ""; // allow re-picking the same file
  };

  // secondary: server-side path entry (large files, no upload copy)
  const openByPath = () => {
    const raw = window.prompt("Open server-side path(s) — separate with ;");
    if (!raw) return;
    const paths = raw
      .split(";")
      .map((p) => p.trim())
      .filter(Boolean);
    if (paths.length) {
      store.openPaths(paths).catch((e: Error) => store.setStatus(e.message));
    }
  };

  // run an analysis returning derived image(s); ingest (undoable) + report
  const derived = (
    label: string,
    run: (id: string) => Promise<ImageMeta[]>,
  ) => {
    const id = store.activeId;
    if (!id) return;
    store.setStatus(`${label}…`);
    run(id)
      .then((metas) => {
        store.ingestDerived(metas);
        store.setStatus(`${label} done`);
      })
      .catch((e: Error) => store.setStatus(`${label}: ${e.message}`));
  };

  // batch crop: the ACTIVE image's ROI (normalized) applied to every
  // selected image — MATLAB doBatchCrop semantics, derived images out
  const runBatchCrop = async () => {
    const a = store.activeId;
    if (!a) return;
    const rois = (store.measures[a] ?? []).filter(
      (m) => m.kind === "roi" || m.kind === "ellipse",
    );
    const roi = rois[rois.length - 1];
    if (!roi) {
      store.setStatus("batch crop: draw an ROI on the active image first");
      return;
    }
    const metas: ImageMeta[] = [];
    let failed = 0;
    for (const id of store.selected) {
      const meta = store.images[id];
      if (!meta) continue;
      const [h, w] = meta.shape;
      const px = (v: number, n: number) =>
        Math.min(n, Math.max(1, Math.round(v * n + 0.5)));
      try {
        metas.push(
          await applyFilter(id, "crop", {
            row0: px(roi.pts[0].y, h),
            col0: px(roi.pts[0].x, w),
            row1: px(roi.pts[1].y, h),
            col1: px(roi.pts[1].x, w),
          }),
        );
      } catch {
        failed++;
      }
    }
    if (metas.length) store.ingestDerived(metas);
    store.setStatus(
      `batch crop: ${metas.length} done` +
        (failed ? `, ${failed} failed` : ""),
    );
  };

  // batch: pick op + params once, run across the filmstrip selection
  const runBatch = async () => {
    const choice = await askParams("Batch Apply", [
      {
        key: "op",
        label: "Operation",
        type: "select",
        default: FILTER_DEFS[0].label,
        options: FILTER_DEFS.map((d) => d.label),
      },
    ]);
    if (!choice) return;
    const def = FILTER_DEFS.find((d) => d.label === choice["op"]);
    if (!def) return;
    const params = def.fields ? await askParams(def.label, def.fields) : {};
    if (params === null) return;
    const targets =
      store.selected.length > 0 ? store.selected : store.order;
    store.setStatus(`batch ${def.kind}…`);
    const metas: ImageMeta[] = [];
    let failed = 0;
    for (const id of targets) {
      try {
        metas.push(
          await applyFilter(id, def.kind, params as Record<string, unknown>),
        );
      } catch {
        failed++;
      }
    }
    if (metas.length) store.ingestDerived(metas);
    store.setStatus(
      `batch ${def.kind}: ${metas.length} done` +
        (failed ? `, ${failed} failed` : ""),
    );
  };

  const filterEntry = (
    label: string,
    kind: string,
    fields?: ParamField[],
  ): Entry => ({
    label,
    disabled: !store.activeId,
    action: () => {
      void (async () => {
        const params = fields ? await askParams(label, fields) : {};
        if (params === null) return; // cancelled
        derived(label, (id) =>
          applyFilter(id, kind, params as Record<string, unknown>).then(
            (m) => [m],
          ),
        );
      })();
    },
  });

  const radialDock = (azimuthal: boolean) => {
    const id = store.activeId;
    if (!id) return;
    analyzeRadial(id, { azimuthal })
      .then((r) => {
        useStageInfo.getState().setProfile({
          measureId: azimuthal ? "__azimuthal__" : "__radial__",
          dist: r.radii,
          intensity: r.intensity,
          length: r.radii[r.radii.length - 1] ?? 0,
          unit: r.unit,
        });
        store.setStatus(
          azimuthal ? "azimuthal integration" : "radial profile",
        );
      })
      .catch((e: Error) => store.setStatus(e.message));
  };

  const menus: Record<string, Entry[]> = {
    File: [
      { label: "Open…", shortcut: "⌘O", action: openFiles },
      { label: "Open by Path…", action: openByPath },
      ...recentPaths().map((p) => ({
        label: `↻ ${p.split(/[\\/]/).pop()}`,
        action: () =>
          store.openPaths([p]).catch((e: Error) => store.setStatus(e.message)),
      })),
      {
        label: "Open RAW…",
        action: () => {
          void (async () => {
            const v = await askParams("Open RAW (headerless binary)", [
              { key: "path", label: "File path", type: "text", default: "" },
              num("width", "Width (px)", 1024),
              num("height", "Height (px)", 1024),
              {
                key: "bits",
                label: "Bit depth",
                type: "select",
                default: "16",
                options: ["8", "16", "32"],
              },
              {
                key: "order",
                label: "Byte order",
                type: "select",
                default: "little",
                options: ["little", "big"],
              },
              num("header", "Header bytes to skip", 0),
            ]);
            if (!v || !v["path"]) return;
            openRaw({
              path: v["path"] as string,
              width: v["width"] as number,
              height: v["height"] as number,
              bitDepth: Number(v["bits"]),
              byteOrder: v["order"] as "little" | "big",
              headerBytes: v["header"] as number,
            })
              .then((m) => store.ingest([m]))
              .catch((e: Error) => store.setStatus(`raw: ${e.message}`));
          })();
        },
      },
      {
        label: `Batch Export… (${store.selected.length})`,
        disabled: store.selected.length < 2,
        action: () => {
          void (async () => {
            const v = await askParams("Batch Export (ZIP)", [
              {
                key: "format",
                label: "Format",
                type: "select",
                default: "png",
                options: ["png", "jpeg", "tiff16"],
              },
              {
                key: "scale",
                label: "Resolution",
                type: "select",
                default: "1",
                options: ["1", "2", "3", "4"],
              },
            ]);
            if (!v) return;
            exportBatch(store.selected, {
              format: v["format"] as string,
              scale: Number(v["scale"]),
            })
              .then((blob) => {
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "export.zip";
                a.click();
                URL.revokeObjectURL(url);
                store.setStatus(
                  `batch exported ${store.selected.length} images`,
                );
              })
              .catch((e: Error) => store.setStatus(`batch: ${e.message}`));
          })();
        },
      },
      {
        label: `Batch Rename… (${store.selected.length})`,
        disabled: store.selected.length < 2,
        action: () => {
          void (async () => {
            const v = await askParams("Batch Rename", [
              {
                key: "prefix",
                label: "Prefix (gets _001, _002…)",
                type: "text",
                default: "frame",
              },
            ]);
            if (!v || !v["prefix"]) return;
            const prefix = v["prefix"] as string;
            let n = 0;
            for (const id of store.selected) {
              n++;
              try {
                const m = await renameImage(
                  id,
                  `${prefix}_${String(n).padStart(3, "0")}`,
                );
                useViewer.setState((s) => ({
                  images: { ...s.images, [m.id]: m },
                }));
              } catch {
                /* keep renaming the rest */
              }
            }
            store.setStatus(`renamed ${n} images`);
          })();
        },
      },
      {
        label: "Save Session…",
        disabled: store.order.length === 0,
        action: () => {
          const p = window.prompt("Save session to path (.json):");
          if (p) {
            store
              .saveWorkspace(p)
              .catch((e: Error) => store.setStatus(e.message));
          }
        },
      },
      {
        label: "Load Session…",
        action: () => {
          const p = window.prompt("Load session from path (.json):");
          if (p) {
            store
              .loadWorkspace(p)
              .catch((e: Error) => store.setStatus(e.message));
          }
        },
      },
      {
        label: "Copy to Clipboard",
        disabled: !store.activeId,
        action: () => {
          const id = store.activeId;
          if (!id) return;
          const d = store.display[id] ?? DD;
          // export mirrors the screen; invert folds into the gray LUT
          const cmap =
            d.invert && d.cmap === "gray" ? "invert" : d.cmap;
          exportImage(id, {
            format: "png",
            scale: 1,
            lo: d.lo,
            hi: d.hi,
            gamma: d.gamma,
            cmap,
            include: [],
          })
            .then(({ blob }) =>
              navigator.clipboard.write([
                new ClipboardItem({ "image/png": blob }),
              ]),
            )
            .then(() => store.setStatus("copied image to clipboard"))
            .catch((e: Error) =>
              store.setStatus(`clipboard: ${e.message}`),
            );
        },
      },
      {
        label: `Export GIF… (${store.selected.length} frames)`,
        disabled: store.selected.length < 2,
        action: () => {
          void (async () => {
            const v = await askParams("Export GIF", [
              num("fps", "Frames per second", 4),
              {
                key: "scale",
                label: "Resolution",
                type: "select",
                default: "1",
                options: ["1", "2", "3", "4"],
              },
              {
                key: "cmap",
                label: "Colormap",
                type: "select",
                default: "gray",
                options: ["gray", "viridis", "inferno", "magma", "plasma"],
              },
            ]);
            if (!v) return;
            exportGif(store.selected, {
              fps: v["fps"] as number,
              scale: Number(v["scale"]),
              cmap: v["cmap"] as string,
            })
              .then(({ blob, filename }) => {
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = filename;
                a.click();
                URL.revokeObjectURL(url);
                store.setStatus(`exported ${filename}`);
              })
              .catch((e: Error) => store.setStatus(`gif: ${e.message}`));
          })();
        },
      },
      {
        label: "Export…",
        shortcut: "⌘E",
        disabled: !store.activeId,
        action: () => store.setExportOpen(true),
      },
      {
        label: "Close Image",
        shortcut: "⌘W",
        disabled: !store.activeId,
        action: () => {
          if (store.activeId) void store.closeImage(store.activeId);
        },
      },
    ],
    Edit: [
      {
        label:
          store.undoStack.length > 0
            ? `Undo ${undoLabel(store.undoStack[store.undoStack.length - 1])}`
            : "Undo",
        shortcut: "⌘Z",
        disabled: store.undoStack.length === 0,
        action: () => {
          const e = store.undo();
          if (e) store.setStatus(`undo: ${undoLabel(e)}`);
        },
      },
      {
        label:
          store.redoStack.length > 0
            ? `Redo ${undoLabel(store.redoStack[store.redoStack.length - 1])}`
            : "Redo",
        shortcut: "⇧⌘Z",
        disabled: store.redoStack.length === 0,
        action: () => {
          const e = store.redo();
          if (e) store.setStatus(`redo: ${undoLabel(e)}`);
        },
      },
      {
        label: "Clear Measurements",
        disabled:
          !store.activeId ||
          (store.measures[store.activeId ?? ""] ?? []).length === 0,
        action: () => {
          if (store.activeId) {
            store.clearMeasures(store.activeId, [
              "distance",
              "profile",
              "angle",
              "roi",
              "ellipse",
              "polyline",
            ]);
            store.setStatus("measurements cleared (undoable)");
          }
        },
      },
      {
        label: "Clear Annotations",
        disabled:
          !store.activeId ||
          (store.measures[store.activeId ?? ""] ?? []).length === 0,
        action: () => {
          if (store.activeId) {
            store.clearMeasures(store.activeId, [
              "text",
              "arrow",
              "box",
              "circle",
            ]);
            store.setStatus("annotations cleared (undoable)");
          }
        },
      },
      {
        label: "Clear All Overlays",
        disabled:
          !store.activeId ||
          (store.measures[store.activeId ?? ""] ?? []).length === 0,
        action: () => {
          if (store.activeId) {
            store.clearMeasures(store.activeId, null);
            store.setStatus("overlays cleared (undoable)");
          }
        },
      },
    ],
    View: [
      { label: "Fit", shortcut: "F", disabled: !store.activeId, action: onFit },
      {
        label: "Actual Size",
        shortcut: "1",
        disabled: !store.activeId,
        action: onActualSize,
      },
      {
        label: store.minimap ? "Hide Minimap" : "Show Minimap",
        action: store.toggleMinimap,
      },
      {
        label: store.colorbar ? "Hide Colorbar" : "Show Colorbar",
        action: store.toggleColorbar,
      },
      {
        label: store.theme === "dark" ? "Light Theme" : "Dark Theme",
        shortcut: "⌘⇧L",
        action: store.toggleTheme,
      },
      {
        label: store.leftCol ? "Show Library" : "Hide Library",
        shortcut: "⌘[",
        action: store.toggleLeft,
      },
      {
        label: store.rightCol ? "Show Inspector" : "Hide Inspector",
        shortcut: "⌘]",
        action: store.toggleRight,
      },
    ],
    Image: [
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
        label: `Batch Crop to ROI (${store.selected.length})`,
        disabled: !store.activeId || store.selected.length < 2,
        action: () => void runBatchCrop(),
      },
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
      ...FILTER_DEFS.slice(0, 7).map((d) =>
        filterEntry(d.label, d.kind, d.fields),
      ),
      {
        label: "Batch Apply…",
        disabled: store.order.length === 0,
        action: () => void runBatch(),
      },
      {
        label: macroRec ? "Stop Macro Recording" : "Record Macro",
        action: () => {
          if (macroRec) {
            const n = stopRecording();
            setMacroRec(false);
            store.setStatus(`macro saved: ${n} step${n === 1 ? "" : "s"}`);
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
        label: "Radial Profile",
        disabled: !store.activeId,
        action: () => radialDock(false),
      },
      {
        label: "Azimuthal Integration",
        disabled: !store.activeId,
        action: () => radialDock(true),
      },
    ],
    Analysis: [
      {
        label: "Particle Analysis…",
        disabled: !store.activeId,
        action: () => {
          void (async () => {
            const v = await askParams("Particle Analysis", [
              num("minArea", "Min area (px)", 10),
              {
                key: "polarity",
                label: "Polarity",
                type: "select",
                default: "bright",
                options: ["bright", "dark"],
              },
              {
                key: "watershed",
                label: "Watershed split",
                type: "boolean",
                default: false,
              },
            ]);
            const id = store.activeId;
            if (!v || !id) return;
            analyzeParticles(id, {
              minArea: v["minArea"] as number,
              watershed: v["watershed"] as boolean,
            })
              .then((r) => {
                store.ingest([r.labels]);
                store.setStatus(
                  `${r.n_particles} particles (threshold ${r.threshold.toPrecision(4)})`,
                );
                useResults.getState().show({
                  title: `Particles — ${r.n_particles} found`,
                  columns: [
                    "#", "area px", "row", "col", "d eq px",
                    "mean I", `area ${r.unit}²`, `d ${r.unit}`,
                  ],
                  rows: r.particles.map((p) => [
                    p.id, p.area, p.centroid[0], p.centroid[1],
                    p.equiv_diameter, p.mean_intensity,
                    p.area_calibrated, p.diameter_calibrated,
                  ]),
                });
              })
              .catch((e: Error) => store.setStatus(e.message));
          })();
        },
      },
      {
        label: "Grain Segmentation…",
        disabled: !store.activeId,
        action: () => {
          void (async () => {
            const v = await askParams("Grain Segmentation", [
              num("k", "Texture classes K", 2),
            ]);
            const id = store.activeId;
            if (!v || !id) return;
            store.setStatus("segmenting grains…");
            type GrainResult = Awaited<ReturnType<typeof analyzeGrains>>;
            runJob<GrainResult>(
              () => analyzeGrainsAsync(id, v["k"] as number),
              (frac, msg) =>
                store.setStatus(
                  `grains: ${msg || "working"} ${(frac * 100).toFixed(0)}%`,
                ),
            )
              .then((r) => {
                store.ingest([r.labels]);
                store.setStatus(
                  `${r.n_grains} grains · mean d ${r.mean_diameter_px.toFixed(1)} px`,
                );
                useResults.getState().show({
                  title: `Grains — ${r.n_grains} found`,
                  columns: ["#", "area px"],
                  rows: r.areas_px.map((a, i) => [i + 1, a]),
                });
              })
              .catch((e: Error) => store.setStatus(e.message));
          })();
        },
      },
      {
        label: "GPA Strain…",
        disabled: !store.activeId,
        action: () => {
          void (async () => {
            const v = await askParams("GPA Strain", [
              num("g1x", "g1 x (FFT px from centre)", 10),
              num("g1y", "g1 y", 0),
              num("g2x", "g2 x", 0),
              num("g2y", "g2 y", 10),
            ]);
            const id = store.activeId;
            if (!v || !id) return;
            store.setStatus("GPA…");
            analyzeGpa(
              id,
              [v["g1x"] as number, v["g1y"] as number],
              [v["g2x"] as number, v["g2y"] as number],
            )
              .then((r) => {
                store.ingest(r.maps);
                store.setStatus(
                  `GPA: exx ${r.mean["exx"].toExponential(2)} · eyy ${r.mean["eyy"].toExponential(2)}`,
                );
              })
              .catch((e: Error) => store.setStatus(e.message));
          })();
        },
      },
      {
        label: "Surface Roughness",
        disabled: !store.activeId,
        action: () => {
          const id = store.activeId;
          if (!id) return;
          analyzeRoughness(id)
            .then((r) => {
              store.setStatus(
                `Ra ${(r["Ra"] as number).toPrecision(4)} · Rq ${(r["Rq"] as number).toPrecision(4)} ${r["unit"]} · SAR ${(r["SAR"] as number).toFixed(4)}`,
              );
            })
            .catch((e: Error) => store.setStatus(e.message));
        },
      },
    ],
    Window: [
      {
        label: "EELS Workshop",
        shortcut: "WINDOW",
        action: () => store.openTool("eels"),
      },
      {
        label: "EDS Composite",
        shortcut: "WINDOW",
        action: () => store.openTool("eds"),
      },
      {
        label: "Diffraction Indexing",
        shortcut: "WINDOW",
        action: () => store.openTool("diffraction"),
      },
      {
        label: "FFT Mask Editor",
        shortcut: "WINDOW",
        action: () => store.openTool("fftmask"),
      },
      {
        label: "Pixel Inspector",
        shortcut: "WINDOW",
        action: () => store.openTool("pixels"),
      },
      {
        label: "Structure Workshop",
        shortcut: "WINDOW",
        action: () => store.openTool("structure"),
      },
      {
        label: "Color Overlay",
        shortcut: "WINDOW",
        action: () => store.openTool("overlay"),
      },
    ],
    Help: [
      {
        label: "Keyboard Shortcuts",
        shortcut: "?",
        action: () => store.setShorts(true),
      },
      {
        label: "Command Palette",
        shortcut: "⌘K",
        action: () => store.setCmdk(true),
      },
    ],
  };

  return (
    <nav className="fvd-menubar" ref={barRef}>
      <input
        ref={fileRef}
        type="file"
        multiple
        accept={accept || undefined}
        style={{ display: "none" }}
        onChange={onFilesPicked}
      />
      {Object.entries(menus).map(([name, entries]) => (
        <div key={name} style={{ position: "relative" }}>
          <div
            className={`fvd-menu-item${open === name ? " open" : ""}`}
            onMouseDown={() => setOpen(open === name ? null : name)}
            onMouseEnter={() => open && setOpen(name)}
          >
            {name}
          </div>
          {open === name && (
            <div className="fvd-menu-dropdown">
              {entries.map((e) => (
                <div
                  key={e.label}
                  className={`fvd-menu-entry${e.disabled ? " disabled" : ""}`}
                  onMouseDown={(ev) => {
                    ev.stopPropagation();
                    setOpen(null);
                    e.action?.();
                  }}
                >
                  <span>{e.label}</span>
                  {e.shortcut && (
                    <span className="fvd-shortcut">{e.shortcut}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
      <span style={{ flex: 1 }} />
      <button
        className="fvd-search-box"
        onClick={() => store.setCmdk(true)}
        title="Command palette"
      >
        <span className="icon">⌕</span> Search actions…
        <span className="fvd-shortcut">⌘K</span>
      </button>
    </nav>
  );
}
