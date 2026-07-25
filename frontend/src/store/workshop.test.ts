import { beforeEach, describe, expect, it } from "vitest";

import { useViewer } from "./viewer";
import { useWorkshop } from "./workshop";
import {
  openCrossSectionGuide,
  openStructureWorkshop,
} from "./workshopNavigation";

beforeEach(() => {
  useViewer.setState({ tools: [] });
  useWorkshop.setState({ structureMode: "Atoms" });
});

describe("workshop navigation intent", () => {
  it.each([
    "Atoms",
    "Particles",
    "Grains",
    "Template",
    "GPA",
    "CTF",
    "Lattice",
    "Stitch",
  ] as const)("deep-links Analysis commands to Structure/%s", (mode) => {
    openStructureWorkshop(mode);

    expect(useWorkshop.getState().structureMode).toBe(mode);
    expect(useViewer.getState().tools).toEqual([
      expect.objectContaining({ kind: "structure" }),
    ]);
  });

  it("opens the guided cross-section workflow", () => {
    openCrossSectionGuide();
    expect(useViewer.getState().tools).toEqual([
      expect.objectContaining({ kind: "crosssection" }),
    ]);
  });
});
