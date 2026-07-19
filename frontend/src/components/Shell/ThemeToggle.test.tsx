import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useAppearancePreviewState } from "../../store/appearancePreview";
import { useViewer } from "../../store/viewer";
import ThemeToggle from "./ThemeToggle";

beforeEach(() => {
  useViewer.setState({ theme: "light" });
  useAppearancePreviewState.getState().setPreview(null);
});

describe("ThemeToggle", () => {
  it("reflects the persisted theme without a preview", () => {
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Dark theme" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("reflects the ephemeral preview theme without changing viewer state", () => {
    useAppearancePreviewState.getState().setPreview({
      theme: "dark",
      accent: "rose",
      density: "compact",
    });
    render(<ThemeToggle />);

    expect(screen.getByRole("button", { name: "Dark theme" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(useViewer.getState().theme).toBe("light");
  });
});
