import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useViewer } from "../../store/viewer";
import { useWorkshop } from "../../store/workshop";
import StructureWorkshop from "./StructureWorkshop";

afterEach(() => {
  useViewer.setState({ activeId: null, images: {}, order: [], selected: [] });
  useWorkshop.setState({ structureMode: "Atoms" });
});

describe("StructureWorkshop navigation", () => {
  it("mounts directly in the requested Grains mode", () => {
    useWorkshop.setState({ structureMode: "Grains" });

    render(<StructureWorkshop />);

    expect(screen.getByRole("button", { name: "Grains" })).toHaveClass(
      "active",
    );
    expect(screen.getByText("Select a 2D image.")).toBeInTheDocument();
  });
});
