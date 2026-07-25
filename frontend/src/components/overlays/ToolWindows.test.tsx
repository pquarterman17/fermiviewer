import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useViewer } from "../../store/viewer";
import ToolWindows from "./ToolWindows";

vi.mock("../workshops/ColorOverlayWorkshop", () => ({
  default: () => <div>Lazy overlay content</div>,
}));
vi.mock("../workshops/StructureWorkshop", () => ({
  default: () => <div>Structure content</div>,
}));
vi.mock("../workshops/CrossSectionGuide", () => ({
  default: () => <div>Cross-section guide content</div>,
}));
vi.mock("../workshops/EdsWorkshop", () => ({
  default: () => <div>EDS workspace content</div>,
}));

beforeEach(() => {
  useViewer.setState({ tools: [] });
});

describe("ToolWindows", () => {
  it("does not mount workshop content until a tool is open", () => {
    render(<ToolWindows />);
    expect(screen.queryByText("Lazy overlay content")).toBeNull();
  });

  it("loads the workshop selected by the open tool", async () => {
    useViewer.setState({ tools: [{ kind: "overlay", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    expect(screen.getByText("Color Overlay")).toBeVisible();
    expect(await screen.findByText("Lazy overlay content")).toBeVisible();
  });

  it("gives the Structure workshop responsive working room", async () => {
    useViewer.setState({ tools: [{ kind: "structure", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    const content = await screen.findByText("Structure content");
    expect(content.closest(".fvd-tool-window")).toHaveStyle({
      width: "480px",
    });
  });

  it("opens the guided cross-section workflow in the widest workshop", async () => {
    useViewer.setState({ tools: [{ kind: "crosssection", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    const content = await screen.findByText("Cross-section guide content");
    expect(screen.getByText("Cross-section Assistant")).toBeVisible();
    expect(content.closest(".fvd-tool-window")).toHaveStyle({ width: "640px" });
  });

  it("gives EDS a wide spectrum-and-map workspace", async () => {
    useViewer.setState({ tools: [{ kind: "eds", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    const content = await screen.findByText("EDS workspace content");
    expect(content.closest(".fvd-tool-window")).toHaveStyle({
      width: "680px",
      height: "620px",
    });
  });

  it("exposes an accessible resize grip", async () => {
    useViewer.setState({ tools: [{ kind: "eds", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    await screen.findByText("EDS workspace content");
    expect(
      screen.getByRole("separator", { name: "Resize EDS window" }),
    ).toBeVisible();
  });
});
