import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BatchRecipePreset } from "../../lib/batchRecipePresets";
import WatchFolderSection from "./WatchFolderSection";

const fetchWatchStatus = vi.fn();
const fetchWatchJob = vi.fn();
const startWatch = vi.fn();
const stopWatch = vi.fn();
vi.mock("../../lib/api", () => ({
  fetchWatchStatus: (...args: unknown[]) => fetchWatchStatus(...args),
  fetchWatchJob: (...args: unknown[]) => fetchWatchJob(...args),
  startWatch: (...args: unknown[]) => startWatch(...args),
  stopWatch: (...args: unknown[]) => stopWatch(...args),
}));

let presets: BatchRecipePreset[] = [];
vi.mock("../../lib/batchRecipePresets", () => ({
  loadBatchRecipePresets: () => presets,
}));

function preset(id: string): BatchRecipePreset {
  return {
    version: 1,
    id,
    name: `Recipe ${id}`,
    steps: [{ op: "denoise", params: {} }],
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
  };
}

beforeEach(() => {
  presets = [];
  fetchWatchStatus.mockResolvedValue({
    watching: false, dir: null, seen: 0, processed: 0,
    last_error: null, job_ids: [],
  });
});

describe("WatchFolderSection — Start button disabled reason", () => {
  it("synthesizes and resets bindings for legacy named-input presets", async () => {
    presets = [
      { ...preset("p1"), steps: [{ op: "image_math", params: {} }] },
      { ...preset("p2"), steps: [{ op: "image_math", params: {} }] },
    ];
    const operations = [{
      name: "image_math", category: "combine", summary: "Combine images",
      produces: "image" as const, params: [],
      inputs: [{
        name: "other", required: true, variadic: false,
        min_count: null, max_count: null, kinds: ["image"], doc: "other image",
      }],
    }];
    const image = { id: "ref", name: "reference.dm4" } as never;
    render(
      <WatchFolderSection
        onDerived={() => undefined}
        operations={operations}
        images={{ ref: image }}
        order={["ref"]}
      />,
    );
    const presetSelect = await screen.findByLabelText("Recipe to watch with");
    fireEvent.change(presetSelect, { target: { value: "p1" } });
    const input = screen.getByLabelText("Watch input other") as HTMLSelectElement;
    fireEvent.change(input, { target: { value: "ref" } });
    expect(input.value).toBe("ref");

    fireEvent.change(presetSelect, { target: { value: "p2" } });
    expect((screen.getByLabelText("Watch input other") as HTMLSelectElement).value).toBe("");
  });

  it("explains that a preset must be saved first when none exist yet", async () => {
    render(<WatchFolderSection onDerived={() => undefined} />);
    await screen.findByLabelText("Folder to watch");
    const start = screen.getByRole("button", { name: "Start" });
    expect(start).toBeDisabled();
    // a disabled button swallows pointer events, so the tip moves to the
    // hoverable wrapper — same pattern as FloatTools' disabled compare button
    expect(start).not.toHaveAttribute("data-tip");
    expect(start.parentElement).toHaveAttribute("data-tip", "Start");
    expect(start.parentElement).toHaveAttribute(
      "data-tip-detail",
      expect.stringContaining("save a recipe as a preset"),
    );
  });

  it("explains a preset needs choosing once directory text is entered", async () => {
    presets = [preset("p1")];
    render(<WatchFolderSection onDerived={() => undefined} />);
    fireEvent.change(await screen.findByLabelText("Folder to watch"), {
      target: { value: "C:\\data\\incoming" },
    });
    const start = screen.getByRole("button", { name: "Start" });
    expect(start).toBeDisabled();
    expect(start.parentElement).toHaveAttribute(
      "data-tip-detail",
      "Choose a saved preset.",
    );
  });

  it("explains a folder path is still needed once a preset is chosen", async () => {
    presets = [preset("p1")];
    render(<WatchFolderSection onDerived={() => undefined} />);
    fireEvent.change(await screen.findByLabelText("Recipe to watch with"), {
      target: { value: "p1" },
    });
    const start = screen.getByRole("button", { name: "Start" });
    expect(start).toBeDisabled();
    expect(start.parentElement).toHaveAttribute(
      "data-tip-detail",
      "Enter a folder path.",
    );
  });

  it("moves the tip back onto the button once Start is actually enabled", async () => {
    presets = [preset("p1")];
    render(<WatchFolderSection onDerived={() => undefined} />);
    fireEvent.change(await screen.findByLabelText("Recipe to watch with"), {
      target: { value: "p1" },
    });
    fireEvent.change(screen.getByLabelText("Folder to watch"), {
      target: { value: "C:\\data\\incoming" },
    });
    const start = screen.getByRole("button", { name: "Start" });
    await waitFor(() => expect(start).toBeEnabled());
    expect(start).toHaveAttribute("data-tip", "Start");
    expect(start.parentElement).not.toHaveAttribute("data-tip");
  });
});

describe("WatchFolderSection — empty preset list hint", () => {
  it("shows an inline hint pointing at the preset Save control when no presets exist", async () => {
    render(<WatchFolderSection onDerived={() => undefined} />);
    await screen.findByLabelText("Folder to watch");
    expect(screen.getByText(/No saved presets yet/)).toBeVisible();
    expect(screen.getByText(/Save new/)).toBeVisible();
  });

  it("hides the hint once at least one preset is saved", async () => {
    presets = [preset("p1")];
    render(<WatchFolderSection onDerived={() => undefined} />);
    await screen.findByLabelText("Folder to watch");
    expect(screen.queryByText(/No saved presets yet/)).toBeNull();
  });
});
