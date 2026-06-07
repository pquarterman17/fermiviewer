// Inline dropdown menu bar (handoff §4 "Menu bar"). Items run inline;
// WINDOW-badged workshop items arrive with Phase 4 tool windows.

import { useEffect, useRef, useState } from "react";

import {
  analyzeGpa,
  analyzeGrains,
  analyzeGrainsAsync,
  analyzeParticles,
  runJob,
  analyzeRadial,
  analyzeRoughness,
  analyzeVdf,
  applyCalibration,
  applyFilter,
  exportImage,
  imageFft,
  supportedExtensions,
  type ImageMeta,
} from "../../lib/api";
import { useStageInfo } from "../../store/stage";
import { DEFAULT_DISPLAY as DD, useViewer } from "../../store/viewer";
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

interface Entry {
  label: string;
  shortcut?: string;
  disabled?: boolean;
  action?: () => void;
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

  // run an analysis returning derived image(s); ingest + report
  const derived = (
    label: string,
    run: (id: string) => Promise<ImageMeta[]>,
  ) => {
    const id = store.activeId;
    if (!id) return;
    store.setStatus(`${label}…`);
    run(id)
      .then((metas) => {
        store.ingest(metas);
        store.setStatus(`${label} done`);
      })
      .catch((e: Error) => store.setStatus(`${label}: ${e.message}`));
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
    View: [
      { label: "Fit", shortcut: "F", disabled: !store.activeId, action: onFit },
      {
        label: "Actual Size",
        shortcut: "1",
        disabled: !store.activeId,
        action: onActualSize,
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
      filterEntry("Gaussian Blur…", "gaussian", [
        num("sigma", "Sigma (px)", 2),
      ]),
      filterEntry("Median Filter…", "median", [
        {
          key: "window_size",
          label: "Window",
          type: "select",
          default: "3",
          options: ["3", "5", "7"],
        },
      ]),
      filterEntry("Unsharp Mask…", "unsharp", [
        num("sigma", "Sigma (px)", 2),
        num("amount", "Amount", 1),
      ]),
      filterEntry("Butterworth…", "butterworth", [
        num("low_cutoff", "Low cutoff (0=off)", 0.05),
        num("high_cutoff", "High cutoff (0–1]", 0.5),
        num("order", "Order", 2),
      ]),
      filterEntry("CLAHE…", "clahe", [
        num("clip_limit", "Clip limit", 0.01),
        num("num_bins", "Bins", 256),
      ]),
      filterEntry("Bin…", "bin", [num("bin_size", "Bin size", 2)]),
      filterEntry("Plane Level", "plane_level"),
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
