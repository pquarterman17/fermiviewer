import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { askParams } from "../../store/params";
import { useViewer } from "../../store/viewer";
import Filmstrip from "./Filmstrip";

vi.mock("../../store/params", () => ({ askParams: vi.fn() }));

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

  it("shows an AFM channel identity separately from the shared filename", () => {
    const afm = {
      ...meta("scan"),
      name: "scan.spm",
      meta: { channel_label: "Height (retrace)" },
    };
    useViewer.setState({
      order: [afm.id],
      activeId: afm.id,
      images: { [afm.id]: afm },
      selected: [afm.id],
    });
    render(<Filmstrip />);
    expect(screen.getByText("scan.spm")).toBeVisible();
    expect(screen.getByText("Height (retrace)")).toBeVisible();
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

  it("keeps one tab stop when no image is active", () => {
    // activeId can be null with images still open (undoing a derived image
    // whose parent is gone). Without a fallback every card would be
    // tabIndex=-1 and the listbox would drop out of the tab order entirely.
    useViewer.setState({ activeId: null });
    render(<Filmstrip />);
    const tabbable = screen
      .getAllByRole("option")
      .filter((o) => o.getAttribute("tabindex") === "0");
    expect(tabbable).toHaveLength(1);
  });

  it("opens and navigates the image context menu from the keyboard", async () => {
    render(<Filmstrip />);
    const option = screen.getAllByRole("option")[0];
    option.focus();
    fireEvent.keyDown(option, { key: "F10", shiftKey: true });

    expect(screen.getByRole("menu", { name: "Image actions" })).toBeVisible();
    const show = screen.getByRole("menuitem", { name: "Show in stage" });
    await waitFor(() => expect(show).toHaveFocus());
    expect(screen.getByRole("menuitem", { name: "Compare selected" })).toBeDisabled();

    expect(
      screen.getByRole("menuitem", { name: "Compare groups side by side" }),
    ).toBeDisabled();

    fireEvent.keyDown(show, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "Group selected…" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "Rename… F2" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("menu", { name: "Image actions" })).toBeNull();
    expect(option).toHaveFocus();
  });
});

describe("Filmstrip grouping", () => {
  beforeEach(() => {
    vi.mocked(askParams).mockReset();
    useViewer.setState({
      order: ["a", "b", "c", "d"],
      activeId: "a",
      images: { a: meta("a"), b: meta("b"), c: meta("c"), d: meta("d") },
      selected: ["a", "b"],
    });
  });

  it("names a group of the selected images from the context menu", async () => {
    vi.mocked(askParams).mockResolvedValue({ name: "Annealed" });
    render(<Filmstrip />);
    fireEvent.contextMenu(screen.getAllByRole("option")[1]);
    fireEvent.click(screen.getByRole("menuitem", { name: "Group selected…" }));

    await waitFor(() =>
      expect(useViewer.getState().imageGroups).toEqual([
        expect.objectContaining({ name: "Annealed", ids: ["a", "b"] }),
      ]),
    );
    expect(askParams).toHaveBeenCalledWith("New group", [
      expect.objectContaining({ key: "name", default: "Group 1" }),
    ]);
  });

  it("creates nothing when the name dialog is cancelled", async () => {
    vi.mocked(askParams).mockResolvedValue(null);
    render(<Filmstrip />);
    fireEvent.contextMenu(screen.getAllByRole("option")[0]);
    fireEvent.click(screen.getByRole("menuitem", { name: "Group selected…" }));
    await waitFor(() => expect(askParams).toHaveBeenCalled());
    expect(useViewer.getState().imageGroups).toEqual([]);
  });

  it("shows each group in its own side-by-side pane", () => {
    useViewer.setState({
      imageGroups: [
        { id: "g1", name: "Before", ids: ["a", "b"] },
        { id: "g2", name: "After", ids: ["c", "d"] },
        { id: "g3", name: "Closed", ids: ["gone"] },
      ],
    });
    render(<Filmstrip />);
    fireEvent.click(screen.getByRole("button", { name: "Side by side" }));

    const s = useViewer.getState();
    expect(s.compareMode).toBe("sidebyside");
    expect(s.sbsPanes.map((p) => p.groupId)).toEqual(["g1", "g2"]);
  });

  it("offers group side-by-side from the context menu once two groups exist", () => {
    useViewer.setState({
      imageGroups: [
        { id: "g1", name: "Before", ids: ["a", "b"] },
        { id: "g2", name: "After", ids: ["c", "d"] },
      ],
    });
    render(<Filmstrip />);
    fireEvent.contextMenu(screen.getAllByRole("option")[0]);
    fireEvent.click(
      screen.getByRole("menuitem", { name: "Compare groups side by side" }),
    );
    expect(useViewer.getState().sbsPanes.map((p) => p.groupId)).toEqual([
      "g1",
      "g2",
    ]);
  });
});
