// Analysis menu builder, split out of MenuBar.tsx (repo-health #33).
// Entries moved verbatim; only `store`/helper references now come from ctx.
import { analyzeBackProject } from "../../../lib/api";
import { askParams } from "../../../store/params";
import {
  openCrossSectionGuide,
  openStructureWorkshop,
} from "../../../store/workshopNavigation";
import type { Entry, MenuCtx } from "./menuTypes";
import { num } from "./menuTypes";

export function buildAnalysisMenu(ctx: MenuCtx): Entry[] {
  const { store, lastProfileMeasure, runBatchProfile } = ctx;
  return [
    {
      label: "Spectroscopy",
      submenu: [
        {
          label: "Elemental Analysis",
          action: () => store.openTool("eds"),
        },
      ],
    },
    {
      label: "Diffraction",
      submenu: [
        {
          label: "Index & Simulate…",
          action: () => store.openTool("diffraction"),
        },
      ],
    },
    {
      label: "4D-STEM",
      submenu: [
        {
          label: "Nav / Pattern Viewer…",
          action: () => store.openTool("fourd"),
        },
      ],
    },
    {
      label: "Structure & Defects",
      submenu: [
        {
          label: "Atom Columns…",
          disabled: !store.activeId,
          action: () => openStructureWorkshop("Atoms"),
        },
        {
          label: "Particles…",
          disabled: !store.activeId,
          action: () => openStructureWorkshop("Particles"),
        },
        {
          label: "Grains…",
          disabled: !store.activeId,
          action: () => openStructureWorkshop("Grains"),
        },
        {
          label: "Template Match…",
          disabled: !store.activeId,
          action: () => openStructureWorkshop("Template"),
        },
        {
          label: "GPA Strain…",
          disabled: !store.activeId,
          action: () => openStructureWorkshop("GPA"),
        },
        {
          label: "CTF Estimate…",
          disabled: !store.activeId,
          action: () => openStructureWorkshop("CTF"),
        },
        {
          label: "Lattice Measurement…",
          disabled: !store.activeId,
          action: () => openStructureWorkshop("Lattice"),
        },
        {
          label: "Stitch Images…",
          disabled: store.selected.length < 2,
          action: () => openStructureWorkshop("Stitch"),
        },
      ],
    },
    {
      label: "Surfaces & Interfaces",
      submenu: [
        {
          label: "Cross-section Assistant…",
          disabled: !store.activeId,
          action: openCrossSectionGuide,
        },
        {
          label: "Layer Analysis…",
          disabled: !store.activeId,
          action: () => store.openTool("layers"),
        },
        {
          label: "Surface Roughness",
          disabled: !store.activeId,
          action: () => store.openTool("roughness"),
        },
        {
          label: "Interface Width…",
          action: () => store.openTool("interface-width"),
        },
      ],
    },
    {
      label: "Image Statistics",
      submenu: [
        {
          label: "Noise Estimate",
          disabled: !store.activeId,
          action: () => store.openTool("noise"),
        },
        {
          label: "Defect Analysis…",
          disabled: !store.activeId,
          action: () => store.openTool("defects"),
        },
        {
          label: `Batch Profile (${store.selected.length} images)`,
          disabled: store.selected.length < 2 || !lastProfileMeasure(),
          action: () => void runBatchProfile(),
        },
      ],
    },
    {
      label: "Reconstruction",
      submenu: [
        {
          label: "Reconstruct Sinogram (FBP)…",
          disabled: !store.activeId,
          action: () => {
            void (async () => {
              const v = await askParams("Reconstruct Sinogram (FBP)", [
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
              store.setStatus("reconstructing sinogram…");
              analyzeBackProject(
                id,
                v["filter"] as "ramp" | "shepp-logan" | "hamming" | "none",
                v["output_size"] as number,
              )
                .then((meta) => {
                  store.ingestDerived([meta]);
                  store.setStatus("sinogram reconstruction done");
                })
                .catch((e: Error) =>
                  store.setStatus(`reconstruction: ${e.message}`),
                );
            })();
          },
        },
      ],
    },
  ];
}
