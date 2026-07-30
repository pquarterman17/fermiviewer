import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EdsElementPicker from "./ElementPicker";

describe("EdsElementPicker", () => {
  beforeEach(() => localStorage.clear());

  it("defaults to the compact dropdown and persists the periodic-table choice", () => {
    render(
      <EdsElementPicker
        selected="(custom)"
        elements={["Fe"]}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByRole("combobox")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Table/ }));
    expect(localStorage.getItem("fv_eds_picker")).toBe("periodic");
    expect(screen.getByRole("grid")).toBeTruthy();
  });

  it("selecting an element in the table fires onSelect", () => {
    const onSelect = vi.fn();
    render(
      <EdsElementPicker
        selected="(custom)"
        elements={[]}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Table/ }));
    fireEvent.click(screen.getByRole("button", { name: "Fe" }));
    expect(onSelect).toHaveBeenCalledWith("Fe");
  });
});
