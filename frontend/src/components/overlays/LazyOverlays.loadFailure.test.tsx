import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useViewer } from "../../store/viewer";
import { expectConsoleError } from "../../test/setup";

// A chunk that cannot be fetched (stale page after an upgrade, backend gone).
vi.mock("./PrefsWindow", () => {
  throw new Error("Failed to fetch dynamically imported module");
});

import LazyOverlays from "./LazyOverlays";

describe("LazyOverlays load failure", () => {
  beforeEach(() => {
    useViewer.setState({ prefsOpen: false });
  });

  it("floats a notice whose Close clears the overlay's open flag", async () => {
    expectConsoleError("using the error boundary you provided, ChunkBoundary");
    expectConsoleError("Preferences failed to load");
    render(<LazyOverlays />);

    act(() => useViewer.setState({ prefsOpen: true }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Preferences failed to load");
    expect(alert).toHaveClass("floating");

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(useViewer.getState().prefsOpen).toBe(false);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
