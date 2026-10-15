import { fireEvent, render, screen } from "@testing-library/react";
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
vi.mock("../workshops/ElementalWorkshop", () => ({
  default: () => <div>Elemental workspace content</div>,
}));
vi.mock("../workshops/DiffractionWorkshop", () => ({
  default: () => <div>Diffraction workspace content</div>,
}));
vi.mock("../workshops/RoughnessWorkshop", () => ({
  default: () => <div>Roughness workspace content</div>,
}));
vi.mock("../workshops/AfmSurfaceWorkshop", () => ({
  default: () => <div>AFM surface content</div>,
}));
vi.mock("../workshops/NoiseWorkshop", () => ({
  default: () => <div>Noise workspace content</div>,
}));
vi.mock("../workshops/InterfaceWidthWorkshop", () => ({
  default: () => <div>Interface width workspace content</div>,
}));
vi.mock("../workshops/DefectWorkshop", () => ({
  default: () => <div>Defect workspace content</div>,
}));
vi.mock("../workshops/ProjectResultsWorkshop", () => ({
  default: () => <div>Saved result cards</div>,
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
    const content = await screen.findByText("Elemental workspace content");
    expect(content.closest(".fvd-tool-window")).toHaveStyle({
      width: "680px",
      height: "620px",
    });
  });

  it.each([
    ["eels", "Elemental workspace content"],
    ["diffraction", "Diffraction workspace content"],
  ] as const)("gives %s a wide tabbed workspace", async (kind, text) => {
    useViewer.setState({ tools: [{ kind, x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    const content = await screen.findByText(text);
    expect(content.closest(".fvd-tool-window")).toHaveStyle({
      width: "680px",
      height: "620px",
    });
  });

  it("gives surface roughness room for metrics and its bearing curve", async () => {
    useViewer.setState({ tools: [{ kind: "roughness", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    const content = await screen.findByText("Roughness workspace content");
    expect(screen.getByText("Surface Roughness")).toBeVisible();
    expect(content.closest(".fvd-tool-window")).toHaveStyle({
      width: "620px",
    });
  });

  it("gives AFM surface analysis a full-workspace control", async () => {
    useViewer.setState({ tools: [{ kind: "afmsurface", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    const content = await screen.findByText("AFM surface content");
    expect(content.closest(".fvd-tool-window")).toHaveStyle({
      width: "620px",
      height: "620px",
    });
    expect(
      screen.getByRole("button", { name: "Use full workspace for Surface Analysis (ISO 25178)" }),
    ).toBeVisible();
  });

  it("gives noise diagnostics room for its evidence plot", async () => {
    useViewer.setState({ tools: [{ kind: "noise", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    const content = await screen.findByText("Noise workspace content");
    expect(screen.getByText("Noise Analysis")).toBeVisible();
    expect(content.closest(".fvd-tool-window")).toHaveStyle({ width: "620px" });
  });

  it("gives interface fitting room for the profile plot", async () => {
    useViewer.setState({
      tools: [{ kind: "interface-width", x: 10, y: 20, z: 1 }],
    });
    render(<ToolWindows />);
    const content = await screen.findByText("Interface width workspace content");
    expect(screen.getByText("Interface Width")).toBeVisible();
    expect(content.closest(".fvd-tool-window")).toHaveStyle({ width: "620px" });
  });

  it("gives defect analysis room for its source-grid preview", async () => {
    useViewer.setState({ tools: [{ kind: "defects", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    const content = await screen.findByText("Defect workspace content");
    expect(screen.getByText("Defect Analysis")).toBeVisible();
    expect(content.closest(".fvd-tool-window")).toHaveStyle({ width: "620px" });
  });

  it("opens the sample comparison panel (real store, no groups yet)", async () => {
    useViewer.setState({
      tools: [{ kind: "projectcompare", x: 10, y: 20, z: 1 }],
      imageGroups: [],
    });
    render(<ToolWindows />);
    expect(screen.getByText("Compare Samples")).toBeVisible();
    expect(await screen.findByText(/No sample groups yet/)).toBeVisible();
  });

  it("gives saved results room for values, warnings and provenance", async () => {
    useViewer.setState({ tools: [{ kind: "results", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    const content = await screen.findByText("Saved result cards");
    expect(screen.getByText("Results & Methods")).toBeVisible();
    expect(content.closest(".fvd-tool-window")).toHaveStyle({
      width: "580px",
      height: "620px",
    });
  });

  it("exposes an accessible resize grip", async () => {
    useViewer.setState({ tools: [{ kind: "eds", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    await screen.findByText("Elemental workspace content");
    expect(
      screen.getByRole("separator", { name: "Resize Elemental Analysis window" }),
    ).toBeVisible();
  });

  it("collapses the elemental workspace without closing it", async () => {
    useViewer.setState({ tools: [{ kind: "eds", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    await screen.findByText("Elemental workspace content");

    fireEvent.click(screen.getByRole("button", { name: "Collapse Elemental Analysis" }));
    expect(screen.getByText("Elemental workspace content")).not.toBeVisible();
    expect(screen.getByText("Elemental Analysis")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Expand Elemental Analysis" }));
    expect(screen.getByText("Elemental workspace content")).toBeVisible();
  });

  it("offers a reversible full-workspace elemental view", async () => {
    useViewer.setState({ tools: [{ kind: "eds", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    const content = await screen.findByText("Elemental workspace content");

    fireEvent.click(screen.getByRole("button", { name: "Use full workspace for Elemental Analysis" }));
    expect(content.closest(".fvd-tool-window")).toHaveClass("expanded");
    expect(content.closest(".fvd-tool-window")).toHaveStyle({
      top: "42px",
      bottom: "32px",
    });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(content.closest(".fvd-tool-window")).not.toHaveClass("expanded");

    fireEvent.click(screen.getByRole("button", { name: "Use full workspace for Elemental Analysis" }));
    fireEvent.click(screen.getByRole("button", { name: "Restore Elemental Analysis window" }));
    expect(content.closest(".fvd-tool-window")).not.toHaveClass("expanded");
  });

  it("restores the preferred elemental size for either modality", async () => {
    localStorage.setItem(
      "fv_tool_size_elemental",
      JSON.stringify({ width: 760, height: 700 }),
    );
    useViewer.setState({ tools: [{ kind: "eels", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    const content = await screen.findByText("Elemental workspace content");
    expect(content.closest(".fvd-tool-window")).toHaveStyle({
      width: "760px",
      height: "700px",
    });
  });

  it("clamps a large saved size to the available viewport", async () => {
    localStorage.setItem(
      "fv_tool_size_elemental",
      JSON.stringify({ width: 2000, height: 1600 }),
    );
    useViewer.setState({ tools: [{ kind: "eds", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    const content = await screen.findByText("Elemental workspace content");
    expect(content.closest(".fvd-tool-window")).toHaveStyle({
      width: `${window.innerWidth - 18}px`,
      height: `${window.innerHeight - 28}px`,
    });
  });

  it("remembers an elemental resize when the drag ends", async () => {
    useViewer.setState({ tools: [{ kind: "eds", x: 10, y: 20, z: 1 }] });
    render(<ToolWindows />);
    const content = await screen.findByText("Elemental workspace content");
    const windowElement = content.closest(".fvd-tool-window") as HTMLElement;
    vi.spyOn(windowElement, "getBoundingClientRect").mockReturnValue({
      width: 680,
      height: 620,
      x: 10,
      y: 20,
      top: 20,
      right: 690,
      bottom: 640,
      left: 10,
      toJSON: () => ({}),
    });
    const grip = screen.getByRole("separator", {
      name: "Resize Elemental Analysis window",
    });
    Object.defineProperties(grip, {
      setPointerCapture: { value: vi.fn() },
      releasePointerCapture: { value: vi.fn() },
    });

    fireEvent.pointerDown(grip, { pointerId: 1, clientX: 680, clientY: 620 });
    fireEvent.pointerMove(grip, { pointerId: 1, clientX: 760, clientY: 700 });
    fireEvent.pointerUp(grip, { pointerId: 1, clientX: 760, clientY: 700 });

    expect(JSON.parse(localStorage.getItem("fv_tool_size_elemental") ?? "null"))
      .toEqual({ width: 760, height: 700 });
  });
});
