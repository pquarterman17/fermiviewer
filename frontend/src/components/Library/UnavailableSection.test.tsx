import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useViewer } from "../../store/viewer";
import UnavailableSection from "./UnavailableSection";

const initialState = useViewer.getState();

beforeEach(() => {
  useViewer.setState(initialState, true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("UnavailableSection", () => {
  it("renders nothing when the project has all its data", () => {
    const { container } = render(<UnavailableSection />);
    expect(container.firstChild).toBeNull();
  });

  it("keeps the name and the stored reference of each placeholder", () => {
    useViewer.setState({
      unavailable: {
        a: {
          id: "a",
          name: "anneal_450C.tif",
          rel: "sampleA/anneal_450C.tif",
          source: "/data/sampleA/anneal_450C.tif",
          size_bytes: 4096,
        },
      },
    });
    render(<UnavailableSection />);
    expect(screen.getByText("1 unavailable")).toBeVisible();
    // the NAME is what the user recognises; the rel is what they match
    // against the folder they are about to pick
    expect(screen.getByText("anneal_450C.tif")).toBeVisible();
    expect(screen.getByText("sampleA/anneal_450C.tif")).toBeVisible();
    // and it says plainly that nothing has been lost
    expect(screen.getByRole("region", { name: "Unavailable images" })
      .textContent).toContain("Nothing is lost");
  });

  it("locates a folder the user picks and can be invoked again", async () => {
    const locateData = vi.fn(() => Promise.resolve());
    useViewer.setState({
      locateData,
      unavailable: {
        a: { id: "a", name: "a.tif", rel: "a.tif", source: null, size_bytes: 1 },
      },
    });
    vi.spyOn(window, "prompt").mockReturnValue("/moved/sampleA");
    render(<UnavailableSection />);

    const button = screen.getByRole("button", { name: /Locate folder/ });
    fireEvent.click(button);
    await vi.waitFor(() => expect(locateData).toHaveBeenCalledWith("/moved/sampleA"));

    // repeatable: the action is not consumed, because a second sample may
    // live in a different folder. It only disables WHILE a pick is in flight.
    await vi.waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);
    await vi.waitFor(() => expect(locateData).toHaveBeenCalledTimes(2));
  });

  it("does nothing when the folder prompt is dismissed", () => {
    const locateData = vi.fn(() => Promise.resolve());
    useViewer.setState({
      locateData,
      unavailable: {
        a: { id: "a", name: "a.tif", rel: "a.tif", source: null, size_bytes: 1 },
      },
    });
    vi.spyOn(window, "prompt").mockReturnValue(null);
    render(<UnavailableSection />);
    fireEvent.click(screen.getByRole("button", { name: /Locate folder/ }));
    expect(locateData).not.toHaveBeenCalled();
  });
});
