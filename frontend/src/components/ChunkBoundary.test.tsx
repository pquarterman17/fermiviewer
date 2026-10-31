import { fireEvent, render, screen } from "@testing-library/react";
import { lazy, type ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { expectConsoleError } from "../test/setup";
import ChunkBoundary from "./ChunkBoundary";

type PanelModule = { default: () => ReactElement };

/** A caught render error is reported twice: React's dev-mode notice and
 *  the boundary's own log line. */
function expectCaughtLoadFailure(): void {
  expectConsoleError("using the error boundary you provided, ChunkBoundary");
  expectConsoleError("Panel failed to load");
}

describe("ChunkBoundary", () => {
  it("shows the fallback while the chunk loads, then the content", async () => {
    let resolve!: (mod: PanelModule) => void;
    const Panel = lazy(() => new Promise<PanelModule>((r) => { resolve = r; }));
    render(
      <ChunkBoundary label="Panel" fallback={<div role="status">Loading panel…</div>}>
        <Panel />
      </ChunkBoundary>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading panel…");
    resolve({ default: () => <div>panel body</div> });
    expect(await screen.findByText("panel body")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("contains a failed chunk load to a notice instead of a blank view", async () => {
    expectCaughtLoadFailure();
    const Panel = lazy(() =>
      Promise.reject(new Error("Failed to fetch dynamically imported module")),
    );
    const onDismiss = vi.fn();
    render(
      <div>
        <div>still here</div>
        <ChunkBoundary label="Panel" onDismiss={onDismiss}>
          <Panel />
        </ChunkBoundary>
      </div>,
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Panel failed to load");
    expect(alert).toHaveTextContent("Failed to fetch dynamically imported module");
    expect(screen.getByText("still here")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("offers no Close without a dismiss handler", async () => {
    expectCaughtLoadFailure();
    const Panel = lazy(() => Promise.reject(new Error("offline")));
    render(
      <ChunkBoundary label="Panel">
        <Panel />
      </ChunkBoundary>,
    );
    await screen.findByRole("alert");
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
  });
});
