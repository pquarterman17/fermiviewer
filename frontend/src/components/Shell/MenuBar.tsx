// Inline dropdown menu bar (handoff §4 "Menu bar"). Items run inline;
// WINDOW-badged workshop items arrive with Phase 4 tool windows.
//
// Decomposed (repo-health #33): each menu group's entries live in
// menus/<group>Menus.ts as a build<Group>Menu(ctx) function. This file
// keeps the component, its local state/effects, every helper closure the
// group builders call into (via `ctx`), and the render JSX.
import { useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";

import {
  analyzeRadial,
  applyCalibration,
  applyFilter,
  measureProfile,
  supportedExtensions,
  type ImageMeta,
} from "../../lib/api";
import { isRecording } from "../../lib/macro";
import { BATCH_FILTERS } from "../../lib/transformTools";
import { useCommands, type Action } from "../../store/commands";
import { askParams } from "../../store/params";
import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";
import { useResults } from "../overlays/ResultsWindow";
import Icon from "../icons/Icon";
import DesktopMenus, { type MenuEntry as Entry } from "./DesktopMenus";
import { buildAnalysisMenu } from "./menus/analysisMenu";
import { buildEditMenu, buildFileMenu } from "./menus/fileEditMenus";
import { buildImageMenu } from "./menus/imageMenu";
import { buildMeasureMenu } from "./menus/measureMenu";
import { menuStoreSelector, num, type MenuCtx } from "./menus/menuTypes";
import {
  buildHelpMenu,
  buildViewMenu,
  buildWindowMenu,
} from "./menus/viewWindowHelpMenus";
import ThemeToggle from "./ThemeToggle";
import WorkspaceSwitcher from "./WorkspaceSwitcher";

export default function MenuBar({
  onFit,
  onActualSize,
}: {
  onFit: () => void;
  onActualSize: () => void;
}) {
  const [accept, setAccept] = useState<string>("");
  const [macroRec, setMacroRec] = useState(isRecording());
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
        // read live — profileWidth isn't part of the narrow render subscription
        const r = await measureProfile(
          id,
          { x: m.pts[0].x * w, y: m.pts[0].y * h },
          { x: m.pts[1].x * w, y: m.pts[1].y * h },
          useViewer.getState().profileWidth,
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
      // read live — selectedMeasure isn't part of the narrow render subscription
      const d =
        dists.find((m) => m.id === useViewer.getState().selectedMeasure) ??
        dists.at(-1);
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
  const fileRef = useRef<HTMLInputElement>(null);
  // narrow selector: only the fields the menu STRUCTURE reads (labels,
  // disabled state, submenu content) + the stable action refs every
  // `store.<action>()` call site below needs. A whole-store `useViewer()`
  // subscription re-rendered this 1,600-line component on every store write
  // (e.g. once per pointermove while panning/zooming, which only touch
  // views/display/tools — fields never read here).
  const store = useViewer(useShallow(menuStoreSelector));

  // active-image doc title + panel-toggle icons live here now (the standalone
  // title bar was removed as redundant — its brand was pure decoration)
  const docName = store.activeId
    ? (store.images[store.activeId]?.name ?? "")
    : "";
  const docStem = docName.replace(/(\.[^.]+)$/, "");
  const docExt = docName.match(/\.[^.]+$/)?.[0] ?? "";

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

  // ⌘O / Ctrl+O opens the picker (a keydown counts as a user gesture);
  // ⌘, / Ctrl+, opens Preferences (the universal Settings shortcut)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey) {
        const k = e.key.toLowerCase();
        if (k === "o") {
          e.preventDefault();
          openFiles();
        } else if (e.key === ",") {
          e.preventDefault();
          useViewer.getState().setPrefsOpen(true);
        }
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
          intensity_sigma: r.intensity_sigma,
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

  const ctx: MenuCtx = {
    store,
    onFit,
    onActualSize,
    openFiles,
    macroRec,
    setMacroRec,
    derived,
    lastProfileMeasure,
    runBatchProfile,
    runBatchCrop,
    runBatch,
    radialDock,
    calibrateFromMeasurement,
  };

  const menus: Record<string, Entry[]> = {
    File: buildFileMenu(ctx),
    Edit: buildEditMenu(ctx),
    View: buildViewMenu(ctx),
    Image: buildImageMenu(ctx),
    Measure: buildMeasureMenu(ctx),
    Analysis: buildAnalysisMenu(ctx),
    Window: buildWindowMenu(ctx),
    Help: buildHelpMenu(ctx),
  };

  // Publish every menu action to the ⌘K palette (single source of truth).
  // Runs every render with NO deps on purpose: `menus` closures capture the
  // current `store` snapshot, so they must be re-published fresh each render
  // rather than cached (a stale closure would read an old store state). No one
  // subscribes to useCommands reactively, so this never triggers re-renders.
  // Now that `store` above is a narrow shallow-selected slice, this effect
  // itself fires far less often too — only on the renders that slice change
  // actually causes, not on every store write (pan/zoom no longer counts).
  useEffect(() => {
    const flat: Action[] = [];
    const publish = (group: string, e: Entry) => {
      if (e.kind || !e.action || !e.label) return; // skip sections/seps
      if (e.label === "Command Palette") return; // self-referential
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
    };
    for (const [group, entries] of Object.entries(menus)) {
      for (const e of entries) {
        // submenu rows have no action of their own — publish their children
        if (e.submenu) e.submenu.forEach((se) => publish(group, se));
        else publish(group, e);
      }
    }
    useCommands.getState().setMenuCommands(flat);
  });

  return (
    <nav className="fvd-menubar">
      <input
        ref={fileRef}
        type="file"
        multiple
        accept={accept || undefined}
        style={{ display: "none" }}
        onChange={onFilesPicked}
      />
      <DesktopMenus menus={menus} />
      <span style={{ flex: 1 }} />
      {store.activeId && (
        <div className="fvd-doc-title">
          {docStem}
          <span className="ext">{docExt}</span>
        </div>
      )}
      <span style={{ flex: 1 }} />
      <button
        className="fvd-icon-btn" aria-label="Keyboard shortcuts"
        data-tip="Keyboard shortcuts"
        data-tip-key="?"
        onClick={() => store.setShorts(true)}
      >
        <Icon name="keyboard" />
      </button>
      <ThemeToggle />
      <button
        className="fvd-icon-btn" aria-label="Library panel" aria-pressed={!store.leftCol}
        data-tip="Toggle library"
        data-tip-key="⌘["
        onClick={store.toggleLeft}
      >
        <Icon name="panel-left" />
      </button>
      <button
        className="fvd-icon-btn" aria-label="Inspector panel" aria-pressed={!store.rightCol}
        data-tip="Toggle inspector"
        data-tip-key="⌘]"
        onClick={store.toggleRight}
      >
        <Icon name="panel-right" />
      </button>
      <WorkspaceSwitcher />
      <button
        className="fvd-search-box" aria-label="Open command palette"
        onClick={() => store.setCmdk(true)}
        title="Command palette"
      >
        <Icon name="search" /> Search actions…
        <span className="fvd-shortcut">⌘K</span>
      </button>
    </nav>
  );
}
