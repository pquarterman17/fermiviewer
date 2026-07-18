import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useViewer } from "../../store/viewer";
import CommandPalette, { type Action } from "./CommandPalette";

const actions: Action[] = [
  { id: "open", label: "Open image", group: "File", run: vi.fn() },
  { id: "reset", label: "Reset view", group: "View", run: vi.fn() },
];

beforeEach(() => {
  useViewer.setState({ cmdk: true });
  vi.clearAllMocks();
});

describe("CommandPalette accessibility", () => {
  it("uses dialog, combobox, and listbox semantics", () => {
    render(<CommandPalette actions={actions} />);
    expect(screen.getByRole("dialog", { name: "Command palette" })).toHaveAttribute(
      "aria-modal",
      "true",
    );
    const input = screen.getByRole("combobox");
    const list = screen.getByRole("listbox");
    expect(input).toHaveAttribute("aria-controls", list.id);
    expect(screen.getAllByRole("option")[0]).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("tracks the active option and executes it with Enter", () => {
    render(<CommandPalette actions={actions} />);
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input).toHaveAttribute("aria-activedescendant", "fvd-command-reset");
    expect(screen.getAllByRole("option")[1]).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.keyDown(input, { key: "Enter" });
    expect(actions[1].run).toHaveBeenCalledOnce();
    expect(useViewer.getState().cmdk).toBe(false);
  });

  it("keeps Tab focus inside and restores the invoking control", async () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    render(<CommandPalette actions={actions} />);
    const input = screen.getByRole("combobox");
    await waitFor(() => expect(input).toHaveFocus());
    fireEvent.keyDown(input, { key: "Tab" });
    expect(input).toHaveFocus();
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => expect(opener).toHaveFocus());
    opener.remove();
  });
});
