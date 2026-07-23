import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EdsElementPicker from "./EdsElementPicker";

describe("EdsElementPicker", () => {
  beforeEach(() => localStorage.clear());

  it("defaults to the periodic table and toggles to the dropdown (persisted)", () => {
    render(
      <EdsElementPicker
        selected="(custom)"
        elements={["Fe"]}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByRole("grid")).toBeTruthy(); // periodic table shown
    fireEvent.click(screen.getByRole("button", { name: /List/ }));
    expect(localStorage.getItem("fv_eds_picker")).toBe("dropdown");
    expect(screen.getByRole("combobox")).toBeTruthy(); // the <select>
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
    fireEvent.click(screen.getByRole("button", { name: "Fe" }));
    expect(onSelect).toHaveBeenCalledWith("Fe");
  });
});
