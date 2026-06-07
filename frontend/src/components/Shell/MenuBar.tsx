// Inline dropdown menu bar (handoff §4 "Menu bar"). Items run inline;
// WINDOW-badged workshop items arrive with Phase 4 tool windows.

import { useEffect, useRef, useState } from "react";

import {
  analyzeGpa,
  analyzeGrains,
  analyzeParticles,
  analyzeRadial,
  analyzeRoughness,
  analyzeVdf,
  applyFilter,
  imageFft,
  supportedExtensions,
  type ImageMeta,
} from "../../lib/api";
import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";

/** Prompt for a number; null = cancelled, default on empty input. */
function askNum(label: string, fallback: number): number | null {
  const raw = window.prompt(label, String(fallback));
  if (raw === null) return null;
  const v = Number(raw);
  return Number.isFinite(v) ? v : fallback;
}

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
    ask?: () => Record<string, unknown> | null,
  ): Entry => ({
    label,
    disabled: !store.activeId,
    action: () => {
      const params = ask ? ask() : {};
      if (params === null) return; // cancelled
      derived(label, (id) =>
        applyFilter(id, kind, params).then((m) => [m]),
      );
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
    Process: [
      {
        label: "FFT",
        disabled: !store.activeId,
        action: () => derived("FFT", (id) => imageFft(id).then((m) => [m])),
      },
      {
        label: "Virtual Dark Field…",
        disabled: !store.activeId,
        action: () => {
          const meta = store.activeId
            ? store.images[store.activeId]
            : undefined;
          const h = meta?.shape[0] ?? 0;
          const w = meta?.shape[1] ?? 0;
          const row = askNum("Mask centre row (FFT px):", Math.round(h / 2));
          if (row === null) return;
          const col = askNum("Mask centre col (FFT px):", Math.round(w / 2));
          if (col === null) return;
          const rad = askNum("Mask radius (px):", 10);
          if (rad === null) return;
          derived("VDF", (id) =>
            analyzeVdf(id, [row, col], rad).then((r) => [r.image]),
          );
        },
      },
      filterEntry("Gaussian Blur…", "gaussian", () => {
        const s = askNum("Sigma (px):", 2);
        return s === null ? null : { sigma: s };
      }),
      filterEntry("Median Filter…", "median", () => {
        const w = askNum("Window (3/5/7):", 3);
        return w === null ? null : { window_size: w };
      }),
      filterEntry("Unsharp Mask…", "unsharp", () => {
        const a = askNum("Amount:", 1);
        return a === null ? null : { amount: a };
      }),
      filterEntry("Butterworth…", "butterworth", () => {
        const lo = askNum("Low cutoff (0–1, 0=off):", 0.05);
        if (lo === null) return null;
        const hi = askNum("High cutoff (0–1]:", 0.5);
        return hi === null ? null : { low_cutoff: lo, high_cutoff: hi };
      }),
      filterEntry("CLAHE", "clahe"),
      filterEntry("Bin 2×", "bin", () => ({ bin_size: 2 })),
      filterEntry("Plane Level", "plane_level"),
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
    Analyze: [
      {
        label: "Particle Analysis…",
        disabled: !store.activeId,
        action: () => {
          const minArea = askNum("Min area (px):", 10);
          if (minArea === null) return;
          const id = store.activeId;
          if (!id) return;
          analyzeParticles(id, { minArea })
            .then((r) => {
              store.ingest([r.labels]);
              store.setStatus(
                `${r.n_particles} particles (threshold ${r.threshold.toPrecision(4)})`,
              );
            })
            .catch((e: Error) => store.setStatus(e.message));
        },
      },
      {
        label: "Grain Segmentation…",
        disabled: !store.activeId,
        action: () => {
          const k = askNum("Number of texture classes K:", 2);
          if (k === null) return;
          const id = store.activeId;
          if (!id) return;
          store.setStatus("segmenting grains…");
          analyzeGrains(id, k)
            .then((r) => {
              store.ingest([r.labels]);
              store.setStatus(
                `${r.n_grains} grains · mean d ${r.mean_diameter_px.toFixed(1)} px`,
              );
            })
            .catch((e: Error) => store.setStatus(e.message));
        },
      },
      {
        label: "GPA Strain…",
        disabled: !store.activeId,
        action: () => {
          const g1x = askNum("g1 x (FFT px from centre):", 10);
          if (g1x === null) return;
          const g1y = askNum("g1 y:", 0);
          if (g1y === null) return;
          const g2x = askNum("g2 x:", 0);
          if (g2x === null) return;
          const g2y = askNum("g2 y:", 10);
          if (g2y === null) return;
          const id = store.activeId;
          if (!id) return;
          store.setStatus("GPA…");
          analyzeGpa(id, [g1x, g1y], [g2x, g2y])
            .then((r) => {
              store.ingest(r.maps);
              store.setStatus(
                `GPA: exx ${r.mean["exx"].toExponential(2)} · eyy ${r.mean["eyy"].toExponential(2)}`,
              );
            })
            .catch((e: Error) => store.setStatus(e.message));
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
        label: "EELS Workshop",
        shortcut: "WINDOW",
        action: () => store.openTool("eels"),
      },
      {
        label: "EDS Workshop",
        shortcut: "WINDOW",
        action: () => store.openTool("eds"),
      },
      {
        label: "Diffraction Workshop",
        shortcut: "WINDOW",
        action: () => store.openTool("diffraction"),
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
    </nav>
  );
}
