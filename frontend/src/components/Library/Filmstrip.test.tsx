import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import Filmstrip from "./Filmstrip";

const meta = (id: string): ImageMeta => ({
  id,
  name: `${id}.dm4`,
  kind: "image",
  shape: [10, 10],
  dtype: "uint8",
  pixel_size: null,
  pixel_unit: "px",
  value_unit: "",
  n_channels: null,
  energy_first: null,
  energy_last: null,
  energy_units: "",
  stage_tilt_deg: null,
  meta: {},
});

beforeEach(() => {
  useViewer.setState({
    order: [],
    activeId: null,
    images: {},
    selected: [],
    imageGroups: [],
    listView: "thumbs",
  });
});

describe("Filmstrip view toggle", () => {
  it("has an action-oriented name and exposes its pressed state", () => {
    render(<Filmstrip />);
    const toggle = screen.getByRole("button", { name: "Show image names" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(toggle.querySelector("svg.fvd-icon")).not.toBeNull();

    fireEvent.click(toggle);
    expect(
      screen.getByRole("button", { name: "Show thumbnails" }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});

describe("Filmstrip keyboard selection", () => {
  beforeEach(() => {
    useViewer.setState({
      order: ["a", "b", "c"],
      activeId: "a",
      images: { a: meta("a"), b: meta("b"), c: meta("c") },
      selected: ["a"],
    });
  });

  it("exposes a multiselect listbox with roving focus", () => {
    render(<Filmstrip />);
    expect(screen.getByRole("listbox", { name: "Open images" })).toHaveAttribute(
      "aria-multiselectable",
      "true",
    );
    const options = screen.getAllByRole("option");
    expect(options[0]).toHaveAttribute("tabindex", "0");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(options[1]).toHaveAttribute("tabindex", "-1");
  });

  it("moves selection with arrows, Home, and End", () => {
    render(<Filmstrip />);
    fireEvent.keyDown(screen.getAllByRole("option")[0], { key: "ArrowDown" });
    expect(useViewer.getState().activeId).toBe("b");
    fireEvent.keyDown(screen.getAllByRole("option")[1], { key: "End" });
    expect(useViewer.getState().activeId).toBe("c");
    fireEvent.keyDown(screen.getAllByRole("option")[2], { key: "Home" });
    expect(useViewer.getState().activeId).toBe("a");
  });

  it("selects the focused image with Enter or Space", () => {
    render(<Filmstrip />);
    const options = screen.getAllByRole("option");
    fireEvent.keyDown(options[1], { key: "Enter" });
    expect(useViewer.getState().selected).toEqual(["b"]);
    fireEvent.keyDown(options[2], { key: " ", ctrlKey: true });
    expect(useViewer.getState().selected).toEqual(["b", "c"]);
  });
});
