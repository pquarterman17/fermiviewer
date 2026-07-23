import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PeriodicTable from "./PeriodicTable";

describe("PeriodicTable", () => {
  it("fires onSelect with the clicked element", () => {
    const onSelect = vi.fn();
    render(
      <PeriodicTable selected={null} present={["Fe"]} onSelect={onSelect} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Fe" }));
    expect(onSelect).toHaveBeenCalledWith("Fe");
  });

  it("marks the selected element pressed", () => {
    render(<PeriodicTable selected="Si" onSelect={() => {}} />);
    expect(
      screen.getByRole("button", { name: "Si" }).getAttribute("aria-pressed"),
    ).toBe("true");
  });
});
