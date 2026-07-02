// Status-bar image cycler (email 2026-07-02 "add buttons to cycle images
// too"): ‹ N / M › prev/next flanking the position counter, shown only when
// more than one image is open.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import StatusBar from "./StatusBar";

const meta = (name: string): ImageMeta =>
  ({
    id: name,
    name,
    kind: "image",
    shape: [10, 10],
    dtype: "uint8",
    pixel_size: null,
    pixel_unit: "px",
    meta: {},
  }) as unknown as ImageMeta;

beforeEach(() => {
  useViewer.setState({
    activeId: "a",
    order: ["a", "b", "c"],
    images: { a: meta("a"), b: meta("b"), c: meta("c") },
    selected: ["a"],
    selectedMeasure: null,
  });
});

describe("StatusBar image cycler", () => {
  it("shows prev/next around the N / M counter with >1 image", () => {
    render(<StatusBar />);
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
    expect(screen.getByText("‹")).toBeInTheDocument();
    expect(screen.getByText("›")).toBeInTheDocument();
  });

  it("steps the active image (next, prev, and wrap)", () => {
    render(<StatusBar />);
    fireEvent.click(screen.getByText("›")); // a -> b
    expect(useViewer.getState().activeId).toBe("b");
    fireEvent.click(screen.getByText("‹")); // b -> a
    expect(useViewer.getState().activeId).toBe("a");
    fireEvent.click(screen.getByText("‹")); // a -> c (wraps)
    expect(useViewer.getState().activeId).toBe("c");
  });

  it("hides the cycler when only one image is open", () => {
    useViewer.setState({ order: ["a"], activeId: "a", images: { a: meta("a") } });
    render(<StatusBar />);
    expect(screen.getByText("1 / 1")).toBeInTheDocument();
    expect(screen.queryByText("‹")).toBeNull();
    expect(screen.queryByText("›")).toBeNull();
  });
});
