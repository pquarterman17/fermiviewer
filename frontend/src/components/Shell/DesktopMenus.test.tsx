import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import DesktopMenus, { type MenuEntry } from "./DesktopMenus";

const action = vi.fn();
const menus: Record<string, MenuEntry[]> = {
  File: [
    { label: "Open", action },
    { kind: "sep" },
    {
      label: "Open recent",
      submenu: [
        { label: "Alpha", action },
        { label: "Unavailable", action, disabled: true },
        { label: "Beta", action },
      ],
    },
  ],
  Edit: [
    { label: "Undo", action, disabled: true },
    { label: "Preferences", action },
  ],
};

describe("DesktopMenus keyboard navigation", () => {
  it("exposes menubar/menu semantics and opens with ArrowDown", async () => {
    render(<DesktopMenus menus={menus} />);
    const file = screen.getByRole("menuitem", { name: "File" });
    expect(screen.getByRole("menubar")).toContainElement(file);
    expect(file).toHaveAttribute("aria-haspopup", "menu");
    expect(file).toHaveAttribute("aria-expanded", "false");
    expect(file).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("menuitem", { name: "Edit" })).toHaveAttribute(
      "tabindex",
      "-1",
    );

    file.focus();
    fireEvent.keyDown(file, { key: "ArrowDown" });
    expect(screen.getByRole("menu", { name: "File" })).toBeVisible();
    await waitFor(() => expect(screen.getByRole("menuitem", { name: "Open" })).toHaveFocus());
    expect(file).toHaveAttribute("aria-expanded", "true");
  });

  it("cycles enabled items and traverses a submenu", async () => {
    render(<DesktopMenus menus={menus} />);
    const file = screen.getByRole("menuitem", { name: "File" });
    fireEvent.keyDown(file, { key: "ArrowDown" });
    const open = screen.getByRole("menuitem", { name: "Open" });
    await waitFor(() => expect(open).toHaveFocus());

    fireEvent.keyDown(open, { key: "ArrowDown" });
    const recent = screen.getByRole("menuitem", { name: "Open recent" });
    expect(recent).toHaveFocus();
    fireEvent.keyDown(recent, { key: "ArrowRight" });
    const alpha = await screen.findByRole("menuitem", { name: "Alpha" });
    await waitFor(() => expect(alpha).toHaveFocus());
    expect(recent).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(alpha, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "Beta" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("menuitem", { name: "Beta" }), {
      key: "ArrowLeft",
    });
    expect(recent).toHaveFocus();
  });

  it("switches top-level menus and restores focus on Escape", async () => {
    render(<DesktopMenus menus={menus} />);
    const file = screen.getByRole("menuitem", { name: "File" });
    fireEvent.keyDown(file, { key: "ArrowDown" });
    const open = screen.getByRole("menuitem", { name: "Open" });
    await waitFor(() => expect(open).toHaveFocus());
    fireEvent.keyDown(open, { key: "ArrowRight" });

    const edit = screen.getByRole("menuitem", { name: "Edit" });
    const preferences = await screen.findByRole("menuitem", {
      name: "Preferences",
    });
    await waitFor(() => expect(preferences).toHaveFocus());
    expect(edit).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(preferences, { key: "Escape" });
    expect(edit).toHaveFocus();
    expect(screen.queryByRole("menu", { name: "Edit" })).toBeNull();
  });
});
