import { beforeEach, describe, expect, it } from "vitest";

import { openGrainWorkshop } from "../components/Shell/MenuBar";
import { useViewer } from "./viewer";
import { useWorkshop } from "./workshop";

beforeEach(() => {
  useViewer.setState({ tools: [] });
  useWorkshop.setState({ structureMode: "Atoms" });
});

describe("workshop navigation intent", () => {
  it("deep-links the Analysis grain command to Structure/Grains", () => {
    openGrainWorkshop();

    expect(useWorkshop.getState().structureMode).toBe("Grains");
    expect(useViewer.getState().tools).toEqual([
      expect.objectContaining({ kind: "structure" }),
    ]);
  });
});
