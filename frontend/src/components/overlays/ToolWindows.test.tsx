import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useViewer } from "../../store/viewer";
import ToolWindows from "./ToolWindows";

vi.mock("../workshops/ColorOverlayWorkshop", () => ({
  default: () => <div>Lazy overlay content</div>,
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
});
