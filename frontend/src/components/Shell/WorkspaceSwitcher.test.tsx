import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listWorkspaces } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import WorkspaceSwitcher from "./WorkspaceSwitcher";

vi.mock("../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/api")>()),
  listWorkspaces: vi.fn(),
  deleteWorkspace: vi.fn(),
}));

const workspaces = [
  { slug: "alpha", name: "Alpha", saved_at: null, n_images: 2 },
  { slug: "beta", name: "Beta", saved_at: null, n_images: 1 },
];

beforeEach(() => {
  vi.mocked(listWorkspaces).mockResolvedValue(workspaces);
  useViewer.setState({ currentWorkspace: { slug: "alpha", name: "Alpha" } });
});

describe("WorkspaceSwitcher menu", () => {
  it("exposes the trigger and active workspace semantically", async () => {
    render(<WorkspaceSwitcher />);
    const trigger = screen.getByRole("button", { name: "Alpha" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);

    expect(await screen.findByRole("menu", { name: "Workspaces" })).toBeVisible();
    expect(screen.getByRole("menuitem", { name: "Alpha" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(
      screen.getByRole("menuitem", { name: "Delete workspace Alpha" }),
    ).toBeVisible();
  });

  it("supports arrow navigation and Escape focus return", async () => {
    render(<WorkspaceSwitcher />);
    const trigger = screen.getByRole("button", { name: "Alpha" });
    fireEvent.click(trigger);
    await screen.findByRole("menuitem", { name: "Beta" });
    fireEvent.click(trigger);

    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const alpha = screen.getByRole("menuitem", { name: "Alpha" });
    await waitFor(() => expect(alpha).toHaveFocus());
    fireEvent.keyDown(alpha, { key: "ArrowDown" });
    expect(
      screen.getByRole("menuitem", { name: "Delete workspace Alpha" }),
    ).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    expect(
      screen.getByRole("menuitem", { name: "Save current layout…" }),
    ).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("menu", { name: "Workspaces" })).toBeNull();
    expect(trigger).toHaveFocus();
  });
});
