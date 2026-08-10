// The filmstrip is ONE panel that grows (W4 #22): these cover the grown
// shape — sections, nesting, collapse, membership drag — plus the invariant
// that matters most, that a library with no groups still renders the bare
// flat list with no section chrome at all.

import { fireEvent, render, screen, within } from "@testing-library/react";
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

const group = (id: string, ids: string[], parent: string | null = null) => ({
  id,
  name: id,
  ids,
  parent,
});

beforeEach(() => {
  localStorage.clear(); // useCollapsedGroups persists collapse per key
  useViewer.setState({
    order: ["a", "b", "c", "d"],
    activeId: "a",
    images: { a: meta("a"), b: meta("b"), c: meta("c"), d: meta("d") },
    selected: ["a"],
    imageGroups: [],
    listView: "names",
  });
});

const listbox = () => screen.getByRole("listbox", { name: "Open images" });
// scoped to the listbox: the GroupsBar chips above it name their groups too
const sectionHead = (name: string) =>
  within(listbox()).getByRole("button", { name: new RegExp(`^${name}`) });
const cardNames = () =>
  screen.getAllByRole("option").map((o) => o.getAttribute("title"));

describe("Filmstrip with no groups", () => {
  it("renders the bare flat list: cards straight in the listbox, no sections", () => {
    render(<Filmstrip />);
    expect(screen.queryAllByRole("group")).toEqual([]);
    expect(document.querySelector(".fvd-sample-section")).toBeNull();
    expect([...listbox().children].map((el) => el.className)).toEqual([
      "fvd-film-card names active selected",
      "fvd-film-card names",
      "fvd-film-card names",
      "fvd-film-card names",
    ]);
    expect(cardNames()).toEqual(["a.dm4", "b.dm4", "c.dm4", "d.dm4"]);
  });

  it("ignores stale collapse state left over from when groups existed", () => {
    // a user who collapsed "Ungrouped" and then deleted every group must not
    // be left staring at an empty filmstrip
    localStorage.setItem("fv_groups_library", JSON.stringify(["__ungrouped__"]));
    render(<Filmstrip />);
    expect(cardNames()).toHaveLength(4);
  });
});

describe("Filmstrip sample sections", () => {
  beforeEach(() => {
    useViewer.setState({
      imageGroups: [
        group("proj", []),
        group("s1", ["a", "b"], "proj"),
        group("s2", ["c"], "proj"),
      ],
    });
  });

  it("renders a section per group, samples nested in their project", () => {
    render(<Filmstrip />);
    const proj = screen.getByRole("group", { name: "proj" });
    expect(proj.querySelector(".fvd-sample-section[aria-label='s1']")).not.toBeNull();
    expect(proj.querySelector(".fvd-sample-section[aria-label='s2']")).not.toBeNull();
    // s1/s2 are nested, proj is not
    expect(proj.className).not.toContain("nested");
    expect(
      screen.getByRole("group", { name: "s1" }).className,
    ).toContain("nested");
  });

  it("puts images in no group under Ungrouped, last", () => {
    render(<Filmstrip />);
    const ungrouped = screen.getByRole("group", { name: "Ungrouped" });
    expect(
      [...ungrouped.querySelectorAll(".fvd-film-card")].map((c) =>
        c.getAttribute("title"),
      ),
    ).toEqual(["d.dm4"]);
    expect(cardNames()).toEqual(["a.dm4", "b.dm4", "c.dm4", "d.dm4"]);
  });

  it("counts every image below a section, so a project counts its samples'", () => {
    render(<Filmstrip />);
    expect(
      sectionHead("proj").textContent,
    ).toContain("3");
  });

  it("collapses a section, hiding its cards", () => {
    render(<Filmstrip />);
    const head = sectionHead("s1");
    expect(head).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(head);
    expect(
      sectionHead("s1"),
    ).toHaveAttribute("aria-expanded", "false");
    expect(cardNames()).toEqual(["c.dm4", "d.dm4"]);
  });

  it("collapsing a project hides its samples too", () => {
    render(<Filmstrip />);
    fireEvent.click(sectionHead("proj"));
    expect(screen.queryByRole("group", { name: "s1" })).toBeNull();
    expect(cardNames()).toEqual(["d.dm4"]);
  });
});

describe("Filmstrip keyboard across sections", () => {
  beforeEach(() => {
    useViewer.setState({
      imageGroups: [group("s1", ["a", "b"]), group("s2", ["c"])],
    });
  });

  it("steps from the last card of one section into the next", () => {
    render(<Filmstrip />);
    const cards = screen.getAllByRole("option");
    fireEvent.keyDown(cards[1], { key: "ArrowDown" }); // b (end of s1) → c (s2)
    expect(useViewer.getState().activeId).toBe("c");
    fireEvent.keyDown(screen.getAllByRole("option")[2], { key: "ArrowDown" });
    expect(useViewer.getState().activeId).toBe("d"); // → Ungrouped
    fireEvent.keyDown(screen.getAllByRole("option")[3], { key: "ArrowDown" });
    expect(useViewer.getState().activeId).toBe("a"); // wraps
  });

  it("End and Home reach the visible ends, not the library's", () => {
    render(<Filmstrip />);
    fireEvent.keyDown(screen.getAllByRole("option")[0], { key: "End" });
    expect(useViewer.getState().activeId).toBe("d");
    fireEvent.keyDown(screen.getAllByRole("option")[3], { key: "Home" });
    expect(useViewer.getState().activeId).toBe("a");
  });

  it("skips a collapsed section instead of focusing a card that isn't there", () => {
    render(<Filmstrip />);
    fireEvent.click(sectionHead("s2"));
    fireEvent.keyDown(screen.getAllByRole("option")[1], { key: "ArrowDown" });
    expect(useViewer.getState().activeId).toBe("d"); // c is hidden
  });

  it("keeps exactly one tab stop with sections in play", () => {
    render(<Filmstrip />);
    const tabbable = screen
      .getAllByRole("option")
      .filter((o) => o.getAttribute("tabindex") === "0");
    expect(tabbable).toHaveLength(1);
    expect(tabbable[0]).toHaveAttribute("title", "a.dm4");
  });
});

describe("Filmstrip membership drag", () => {
  beforeEach(() => {
    useViewer.setState({
      imageGroups: [group("s1", ["a", "b"]), group("s2", ["c"])],
    });
  });

  const cardFor = (name: string) =>
    screen.getAllByRole("option").find((o) => o.getAttribute("title") === name)!;
  const drag = (from: HTMLElement, onto: HTMLElement) => {
    fireEvent.dragStart(from, { dataTransfer: {} });
    fireEvent.dragOver(onto, { dataTransfer: {} });
    fireEvent.drop(onto, { dataTransfer: {} });
  };

  it("moves an image between sections instead of reordering it", () => {
    render(<Filmstrip />);
    drag(cardFor("a.dm4"), cardFor("c.dm4"));
    const groups = useViewer.getState().imageGroups;
    expect(groups.find((g) => g.id === "s1")?.ids).toEqual(["b"]);
    expect(groups.find((g) => g.id === "s2")?.ids).toEqual(["c", "a"]);
    // library order is untouched — a cross-section drop is a membership edit
    expect(useViewer.getState().order).toEqual(["a", "b", "c", "d"]);
  });

  it("drops onto a section's own chrome, so a collapsed sample is reachable", () => {
    render(<Filmstrip />);
    fireEvent.click(sectionHead("s2"));
    fireEvent.dragStart(cardFor("a.dm4"), { dataTransfer: {} });
    fireEvent.drop(screen.getByRole("group", { name: "s2" }), { dataTransfer: {} });
    expect(
      useViewer.getState().imageGroups.find((g) => g.id === "s2")?.ids,
    ).toEqual(["c", "a"]);
  });

  it("dragging out to Ungrouped only removes membership", () => {
    render(<Filmstrip />);
    drag(cardFor("a.dm4"), cardFor("d.dm4"));
    const groups = useViewer.getState().imageGroups;
    expect(groups.find((g) => g.id === "s1")?.ids).toEqual(["b"]);
    expect(groups.map((g) => g.id)).toEqual(["s1", "s2"]); // no group invented
  });

  it("still reorders when the drag stays inside one section", () => {
    render(<Filmstrip />);
    drag(cardFor("b.dm4"), cardFor("a.dm4"));
    expect(useViewer.getState().order).toEqual(["b", "a", "c", "d"]);
    expect(
      useViewer.getState().imageGroups.find((g) => g.id === "s1")?.ids,
    ).toEqual(["a", "b"]); // membership untouched
  });
});
