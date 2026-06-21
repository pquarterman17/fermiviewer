// Inline dropdown menu bar (handoff §4 "Menu bar"). Items run inline;
// WINDOW-badged workshop items arrive with Phase 4 tool windows.

import { useEffect, useRef, useState } from "react";

import {
  analyzeAlignStack,
  analyzeBackProject,
  analyzeGpa,
  analyzeGrains,
  analyzeGrainsAsync,
  analyzeImageMath,
  analyzeMip,
  analyzeMontage,
  analyzeParticles,
  runJob,
  analyzeDefects,
  analyzeInterfaceWidth,
  analyzeNoise,
  analyzeRadial,
  measureProfile,
  analyzeRoughness,
  analyzeVdf,
  applyCalibration,
  applyFilter,
  detectScaleBar,
  explodeStack,
  exportBatch,
  exportFigure,
  exportGif,
  renameImage,
  imageFft,
  supportedExtensions,
  type ImageMeta,
} from "../../lib/api";
import { downloadBugReport } from "../../lib/errlog";
import { copyActive } from "../../lib/export";
import {
  isRecording,
  loadMacro,
  replayMacro,
  startRecording,
  stopRecording,
} from "../../lib/macro";
import { applyGeometry, cropToRoi } from "../../lib/stageOps";
import { BATCH_FILTERS } from "../../lib/transformTools";
import { useCommands, type Action } from "../../store/commands";
import { useStageInfo } from "../../store/stage";
import { undoLabel, useViewer } from "../../store/viewer";
import {
  askParams,
  type ParamField,
} from "../overlays/ParamDialog";
import { useResults } from "../overlays/ResultsWindow";
import WorkspaceSwitcher from "./WorkspaceSwitcher";

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
  label?: string;
  shortcut?: string;
  disabled?: boolean;
  action?: () => void;
  /** "section" = an uppercase group heading; "sep" = a hairline divider.
   *  Omitted = a normal action row. */
  kind?: "section" | "sep";
}

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
  const profile = useStageInfo((s) => s.profile);

  // latest profile-like measure on the active image (batch profile)
  const lastProfileMeasure = () => {
    const id = store.activeId;
    if (!id) return undefined;
    return (store.measures[id] ?? [])
      .filter((m) => m.kind === "profile" || m.kind === "distance")
      .at(-1);
  };

  // same normalized line sampled across every selected image → one
  // CSV-able table (distance + a column per image)
  const runBatchProfile = async () => {
    const m = lastProfileMeasure();
    if (!m || store.selected.length < 2) return;
    store.setStatus("batch profile…");
    const columns = ["distance"];
    const series: (number | null)[][] = [];
    let dist: number[] | null = null;
    for (const id of store.selected) {
      const meta = store.images[id];
      if (!meta) continue;
      const [h, w] = meta.shape;
      try {
        const r = await measureProfile(
          id,
          { x: m.pts[0].x * w, y: m.pts[0].y * h },
          { x: m.pts[1].x * w, y: m.pts[1].y * h },
          store.profileWidth,
          null,
          useViewer.getState().profileReduce,
        );
        dist ??= r.dist;
        columns.push(meta.name);
        series.push(r.intensity);
      } catch {
        /* skip images the profile fails on (e.g. spectra) */
      }
    }
    if (!dist || series.length === 0) {
      store.setStatus("batch profile: no usable images");
      return;
    }
    const n = Math.min(dist.length, ...series.map((s) => s.length));
    useResults.getState().show({
      title: `Batch profile (${series.length} images)`,
      columns,
      rows: Array.from({ length: n }, (_, i) => [
        Number(dist![i].toPrecision(6)),
        ...series.map((s) => s[i]),
      ]),
    });
    store.setStatus(`batch profile: ${series.length} images`);
  };
  // calibrate the active image's pixel size from its last distance measure —
  // shared by the Image ▸ Calibration and Measure ▸ Calibration entries
  const calibrateFromMeasurement = () => {
    void (async () => {
      const id = store.activeId;
      if (!id) return;
      const meta = store.images[id];
      // prefer the SELECTED distance line; fall back to the last one drawn
      const dists = (store.measures[id] ?? []).filter(
        (m) => m.kind === "distance",
      );
      const d = dists.find((m) => m.id === store.selectedMeasure) ?? dists.at(-1);
      if (!meta || !d) return;
      const [h, w] = meta.shape;
      const lenPx = Math.hypot(
        (d.pts[1].x - d.pts[0].x) * w,
        (d.pts[1].y - d.pts[0].y) * h,
      );
      // guard BEFORE the dialog so a zero-length line doesn't waste the
      // user's input and then silently no-op
      if (lenPx <= 0) {
        store.setStatus("calibration line has zero length — redraw it");
        return;
      }
      const v = await askParams(`Calibrate (measured ${lenPx.toFixed(1)} px)`, [
        num("len", "Known physical length", 1),
        {
          key: "unit",
          label: "Unit",
          type: "select",
          default: "nm",
          options: ["nm", "µm", "Å", "pm", "mm"],
        },
      ]);
      if (!v) return;
      applyCalibration(id, (v["len"] as number) / lenPx, v["unit"] as string)
        .then((r) => {
          useViewer.setState((s) => ({
            images: { ...s.images, [r.image.id]: r.image },
          }));
          store.removeMeasure(id, d.id); // the calibration line disappears
          store.setStatus(
            `calibrated: ${r.image.pixel_size?.toPrecision(4)} ` +
              `${r.image.pixel_unit}/px`,
          );
        })
        .catch((e: Error) => store.setStatus(e.message));
    })();
  };
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

  // Open: when launched from a folder of images, show that folder's
  // files (pre-pointed); otherwise the OS-native picker → multipart
  // upload. getState() so the ⌘O handler reads the live launch context.
  const openFiles = () => {
    const s = useViewer.getState();
    if ((s.launchContext?.files.length ?? 0) > 0) s.setFolderOpen(true);
    else fileRef.current?.click();
  };

  // ⌘O / Ctrl+O opens the picker (a keydown counts as a user gesture)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "o") {
        e.preventDefault();
        openFiles();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onFilesPicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      store.openFiles(files).catch((err: Error) => store.setStatus(err.message));
    }
    e.target.value = ""; // allow re-picking the same file
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
        default: BATCH_FILTERS[0].label,
        options: BATCH_FILTERS.map((d) => d.label),
      },
    ]);
    if (!choice) return;
    const def = BATCH_FILTERS.find((d) => d.label === choice["op"]);
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
          reduce: "mean",
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
      ...recentPaths().map((p) => ({
        label: `↻ ${p.split(/[\\/]/).pop()}`,
        action: () =>
          store.openPaths([p]).catch((e: Error) => store.setStatus(e.message)),
      })),
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
        label: `Export Figure Panel… (${store.selected.length})`,
        disabled: store.selected.length < 2,
        action: () => {
          void (async () => {
            const v = await askParams("Figure panel (labeled grid)", [
              num("cols", "Columns (0 = auto)", 0),
              num("gap", "Gap (px)", 4),
              {
                key: "scale",
                label: "Resolution",
                type: "select",
                default: "1",
                options: ["1", "2", "3", "4"],
              },
            ]);
            if (!v) return;
            exportFigure(store.selected, {
              cols: v["cols"] as number,
              gap: v["gap"] as number,
              scale: Number(v["scale"]),
            })
              .then((blob) => {
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "figure.png";
                a.click();
                URL.revokeObjectURL(url);
                store.setStatus(
                  `figure panel: ${store.selected.length} panels`,
                );
              })
              .catch((e: Error) => store.setStatus(`figure: ${e.message}`));
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
          // shared with the radial "Copy": bakes scale bar + measurements
          // by default so both copy paths behave identically
          copyActive()
            .then(() =>
              store.setStatus("copied to clipboard (scale bar + measurements)"),
            )
            .catch((e: Error) => store.setStatus(`clipboard: ${e.message}`));
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
        label: store.scaleBarVisible ? "Hide Scale Bar" : "Show Scale Bar",
        disabled: !store.activeId,
        action: store.toggleScaleBar,
      },
      {
        label: "Image Gallery",
        shortcut: "V",
        disabled: store.order.length === 0,
        action: () => store.setGalleryOpen(true),
      },
      {
        label: "Side-by-side Compare",
        disabled: store.order.length === 0,
        action: store.startSideBySide,
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
        label: "Preferences…",
        action: () => store.setPrefsOpen(true),
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
      { kind: "section", label: "Transform" },
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
      { kind: "section", label: "Combine" },
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
      { kind: "section", label: "Stack" },
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
      { kind: "section", label: "Fourier" },
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
      { kind: "section", label: "Batch & macro" },
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
      { kind: "section", label: "Calibration" },
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
      { kind: "section", label: "Profiles" },
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
    Measure: [
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
              () =>
                analyzeGrainsAsync(id, {
                  method: "kmeans",
                  k: v["k"] as number,
                }),
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
      {
        label: "Interface Width (fit dock profile)",
        disabled: !profile,
        action: () => {
          if (!profile) return;
          analyzeInterfaceWidth(profile.dist, profile.intensity)
            .then((r) =>
              store.setStatus(
                `interface: 10–90% width ${r.width_10_90.toPrecision(4)} ` +
                  `${profile.unit} · σ ${r.sigma.toPrecision(4)} · ` +
                  `R² ${r.r_squared.toFixed(3)}`,
              ),
            )
            .catch((e: Error) => store.setStatus(`interface: ${e.message}`));
        },
      },
      {
        label: "Noise Estimate",
        disabled: !store.activeId,
        action: () => {
          const id = store.activeId;
          if (!id) return;
          analyzeNoise(id)
            .then((r) =>
              store.setStatus(
                `noise: σ ${r.sigma.toPrecision(4)} · ` +
                  `SNR ${r.snr_db.toFixed(1)} dB (${r.noise_type}) → ` +
                  `try ${r.recommendation}`,
              ),
            )
            .catch((e: Error) => store.setStatus(`noise: ${e.message}`));
        },
      },
      {
        label: "Defect Count",
        disabled: !store.activeId,
        action: () => {
          const id = store.activeId;
          if (!id) return;
          analyzeDefects(id)
            .then((r) => {
              store.ingestDerived([r.enhanced]);
              store.setStatus(
                `defects: ${r.intersections} intercepts on ` +
                  `${r.test_lines} lines · ρ ${r.density.toExponential(2)} ` +
                  r.density_unit,
              );
            })
            .catch((e: Error) => store.setStatus(`defects: ${e.message}`));
        },
      },
      {
        label: `Batch Profile (${store.selected.length} images)`,
        disabled: store.selected.length < 2 || !lastProfileMeasure(),
        action: () => void runBatchProfile(),
      },
      {
        label: "Back Project (FBP)…",
        disabled: !store.activeId,
        action: () => {
          void (async () => {
            const v = await askParams("Filtered Back-Projection", [
              {
                key: "filter",
                label: "Filter",
                type: "select",
                default: "ramp",
                options: ["ramp", "shepp-logan", "hamming", "none"],
              },
              num("output_size", "Output size (0 = auto)", 0),
            ]);
            const id = store.activeId;
            if (!v || !id) return;
            store.setStatus("back-project…");
            analyzeBackProject(
              id,
              v["filter"] as "ramp" | "shepp-logan" | "hamming" | "none",
              v["output_size"] as number,
            )
              .then((m) => {
                store.ingestDerived([m]);
                store.setStatus("back-project done");
              })
              .catch((e: Error) => store.setStatus(`back-project: ${e.message}`));
          })();
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
      {
        label: "Surface Plot",
        shortcut: "WINDOW",
        action: () => store.openTool("surface"),
      },
    ],
    Help: [
      {
        label: "Keyboard Shortcuts",
        shortcut: "?",
        action: () => store.setShorts(true),
      },
      {
        label: "Report a Bug…",
        action: () => {
          downloadBugReport()
            .then(() =>
              store.setStatus(
                "bug report downloaded — attach it to your issue",
              ),
            )
            .catch((e: Error) => store.setStatus(`report: ${e.message}`));
        },
      },
      {
        // Manual fallback for the desktop auto-updater: opens the latest
        // GitHub Release (the runnable installer lives there). target=_blank
        // → new tab in the browser app, system browser in the Tauri shell;
        // the app window never navigates away.
        label: "Check for Updates…",
        action: () => {
          window.open(
            "https://github.com/pquarterman17/fermiviewer/releases/latest",
            "_blank",
            "noopener",
          );
          store.setStatus("opened the latest release page in your browser");
        },
      },
      {
        label: "Command Palette",
        shortcut: "⌘K",
        action: () => store.setCmdk(true),
      },
    ],
  };

  // Publish every menu action to the ⌘K palette (single source of truth).
  // Runs every render with NO deps on purpose: `menus` closures capture the
  // current `store` snapshot, so they must be re-published fresh each render
  // rather than cached (a stale closure would read an old store state). No one
  // subscribes to useCommands reactively, so this never triggers re-renders.
  useEffect(() => {
    const flat: Action[] = [];
    for (const [group, entries] of Object.entries(menus)) {
      for (const e of entries) {
        if (e.kind || !e.action || !e.label) continue; // skip sections/seps
        if (e.label === "Command Palette") continue; // self-referential
        // sentinel tags like "WINDOW" are not real key hints
        const sc =
          e.shortcut && !/^[A-Z]{3,}$/.test(e.shortcut) ? e.shortcut : undefined;
        flat.push({
          id: `menu:${group}:${e.label}`,
          group,
          label: e.label,
          shortcut: sc,
          run: e.action,
        });
      }
    }
    useCommands.getState().setMenuCommands(flat);
  });

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
              {entries.map((e, i) => {
                if (e.kind === "sep")
                  return <div key={i} className="fvd-menu-sep" />;
                if (e.kind === "section")
                  return (
                    <div key={i} className="fvd-menu-section">
                      {e.label}
                    </div>
                  );
                return (
                  <div
                    key={i}
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
                );
              })}
            </div>
          )}
        </div>
      ))}
      <span style={{ flex: 1 }} />
      <WorkspaceSwitcher />
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
