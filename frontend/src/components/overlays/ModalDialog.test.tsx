import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import ModalDialog from "./ModalDialog";

function Fixture({ onClose = () => undefined }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Open dialog</button>
      {open && (
        <ModalDialog
          ariaLabel="Test dialog"
          className="test-dialog"
          onClose={() => {
            onClose();
            setOpen(false);
          }}
        >
          <button>First</button>
          <button>Last</button>
        </ModalDialog>
      )}
    </>
  );
}

describe("ModalDialog", () => {
  it("provides modal semantics and focuses the first control", async () => {
    render(<Fixture />);
    fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));
    expect(screen.getByRole("dialog", { name: "Test dialog" })).toHaveAttribute(
      "aria-modal",
      "true",
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "First" })).toHaveFocus());
  });

  it("wraps focus in both directions", async () => {
    render(<Fixture />);
    fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));
    const dialog = screen.getByRole("dialog", { name: "Test dialog" });
    const first = screen.getByRole("button", { name: "First" });
    const last = screen.getByRole("button", { name: "Last" });
    await waitFor(() => expect(first).toHaveFocus());
    last.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });

  it("closes with Escape and restores focus to the opener", async () => {
    const onClose = vi.fn();
    render(<Fixture onClose={onClose} />);
    const opener = screen.getByRole("button", { name: "Open dialog" });
    opener.focus();
    fireEvent.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Test dialog" });
    await waitFor(() => expect(screen.getByRole("button", { name: "First" })).toHaveFocus());
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("only closes when the backdrop itself is pressed", () => {
    const onClose = vi.fn();
    render(<Fixture onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));
    const dialog = screen.getByRole("dialog", { name: "Test dialog" });
    fireEvent.mouseDown(dialog);
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.mouseDown(dialog.parentElement!);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
