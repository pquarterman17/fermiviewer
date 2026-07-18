import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useViewer } from "../../store/viewer";
import Filmstrip from "./Filmstrip";

beforeEach(() => {
  useViewer.setState({
    order: [],
    activeId: null,
    images: {},
    selected: [],
    imageGroups: [],
    listView: "thumbs",
  });
});

describe("Filmstrip view toggle", () => {
  it("has an action-oriented name and exposes its pressed state", () => {
    render(<Filmstrip />);
    const toggle = screen.getByRole("button", { name: "Show image names" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(toggle);
    expect(
      screen.getByRole("button", { name: "Show thumbnails" }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});
