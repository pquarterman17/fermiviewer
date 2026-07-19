import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SpectrumNavigationControl from "./SpectrumNavigationControl";

describe("SpectrumNavigationControl", () => {
  it("presents an accessible inactive action", () => {
    render(
      <SpectrumNavigationControl
        active={false}
        pixel={null}
        onToggle={() => {}}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Start live stage probe" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByText("Explore spectra from the main image"),
    ).toBeInTheDocument();
  });

  it("shows the active pixel and invokes the toggle", () => {
    const onToggle = vi.fn();
    render(<SpectrumNavigationControl active pixel={[17, 23]} onToggle={onToggle} />);

    const stop = screen.getByRole("button", { name: "Stop live stage probe" });
    expect(stop).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Row 17 · Col 23")).toBeInTheDocument();
    fireEvent.click(stop);
    expect(onToggle).toHaveBeenCalledOnce();
  });
});
