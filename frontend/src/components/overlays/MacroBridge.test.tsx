import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const macroOpSteps = vi.fn();
const macroLegacyCount = vi.fn();
const setMacroFromRecipe = vi.fn();
vi.mock("../../lib/macro", () => ({
  macroOpSteps: (...args: unknown[]) => macroOpSteps(...args),
  macroLegacyCount: (...args: unknown[]) => macroLegacyCount(...args),
  setMacroFromRecipe: (...args: unknown[]) => setMacroFromRecipe(...args),
}));

import MacroBridge from "./MacroBridge";

describe("MacroBridge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads the macro's op steps into the dialog via onLoad", () => {
    macroOpSteps.mockReturnValue([{ op: "gaussian", params: { sigma: 2 } }]);
    macroLegacyCount.mockReturnValue(0);
    const onLoad = vi.fn();
    render(<MacroBridge steps={[]} disabled={false} onLoad={onLoad} />);

    fireEvent.click(screen.getByText("Load Recorded Macro"));

    expect(onLoad).toHaveBeenCalledWith([{ op: "gaussian", params: { sigma: 2 } }]);
    expect(screen.getByText(/Loaded 1 step from the macro/)).toBeVisible();
  });

  it("reports skipped legacy steps and a load error", () => {
    macroOpSteps.mockReturnValue([{ op: "gaussian", params: {} }]);
    macroLegacyCount.mockReturnValue(2);
    const onLoad = vi.fn().mockReturnValue("Unavailable operation: gaussian");
    render(<MacroBridge steps={[]} disabled={false} onLoad={onLoad} />);

    fireEvent.click(screen.getByText("Load Recorded Macro"));

    expect(screen.getByText("Unavailable operation: gaussian")).toBeVisible();
  });

  it("reports when the macro has no batchable steps", () => {
    macroOpSteps.mockReturnValue([]);
    render(<MacroBridge steps={[]} disabled={false} onLoad={vi.fn()} />);

    fireEvent.click(screen.getByText("Load Recorded Macro"));

    expect(
      screen.getByText("No batchable steps in the recorded macro"),
    ).toBeVisible();
  });

  it("saves the current dialog steps as the recorded macro", () => {
    setMacroFromRecipe.mockReturnValue({ n: 2, persisted: true });
    const steps = [
      { op: "gaussian", params: { sigma: 2 } },
      { op: "flipv", params: {} },
    ];
    render(<MacroBridge steps={steps} disabled={false} onLoad={vi.fn()} />);

    fireEvent.click(screen.getByText("Save Steps as Macro"));

    expect(setMacroFromRecipe).toHaveBeenCalledWith(steps, {});
    expect(screen.getByText(/Saved 2 steps as the recorded macro/)).toBeVisible();
  });

  it("requires bindings before saving a named-input macro", () => {
    const steps = [{
      op: "image_math", params: {}, inputs: { other: "reference" },
    }];
    render(<MacroBridge steps={steps} disabled={false} onLoad={vi.fn()} />);

    fireEvent.click(screen.getByText("Save Steps as Macro"));

    expect(setMacroFromRecipe).not.toHaveBeenCalled();
    expect(screen.getByText(/Choose every recipe input/)).toBeVisible();
  });

  it("reports when saving the macro fails to persist (e.g. storage full)", () => {
    setMacroFromRecipe.mockReturnValue({ n: 2, persisted: false });
    const steps = [{ op: "gaussian", params: { sigma: 2 } }];
    render(<MacroBridge steps={steps} disabled={false} onLoad={vi.fn()} />);

    fireEvent.click(screen.getByText("Save Steps as Macro"));

    expect(
      screen.getByText("Could not save the macro (storage full or unavailable)"),
    ).toBeVisible();
  });

  it("disables save when there are no steps", () => {
    render(<MacroBridge steps={[]} disabled={false} onLoad={vi.fn()} />);
    expect(screen.getByText("Save Steps as Macro")).toBeDisabled();
  });
});
