// PrefsWindow: sectioned settings window. Store is mocked; localStorage
// (jsdom) backs the real loadPrefs/savePrefs so we can assert persistence.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadPrefs } from "../../lib/prefs";

const state = {
  prefsOpen: true,
  setPrefsOpen: vi.fn(),
  setStatus: vi.fn(),
  // apply-live action setters invoked by save()
  setTheme: vi.fn(),
  setToolsLayout: vi.fn(),
  setProfileWidth: vi.fn(),
  setProfileReduce: vi.fn(),
  setColorbarSide: vi.fn(),
  setScaleBarVisible: vi.fn(),
  setOverlay: vi.fn(),
};

vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign((sel: (s: typeof state) => unknown) => sel(state), {
    getState: () => state,
  }),
}));

vi.mock("../../lib/colormaps", () => ({
  setCustomColormap: vi.fn(() => true),
}));

import PrefsWindow from "./PrefsWindow";

describe("PrefsWindow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("renders the section nav and the Appearance pane by default", () => {
    render(<PrefsWindow />);
    expect(screen.getByText("Preferences")).toBeInTheDocument();
    expect(screen.getByText("Appearance")).toBeInTheDocument();
    expect(screen.getByText("Export")).toBeInTheDocument();
    // Appearance content
    expect(screen.getByText("Theme")).toBeInTheDocument();
    // Export content is not mounted until that section is selected
    expect(screen.queryByText("Bake scale bar by default")).toBeNull();
  });

  it("switches sections via the left nav", () => {
    render(<PrefsWindow />);
    fireEvent.click(screen.getByText("Export"));
    expect(screen.getByText("Bake scale bar by default")).toBeInTheDocument();
    expect(screen.queryByText("Theme")).toBeNull();
  });

  it("Save persists the draft and applies live fields", () => {
    render(<PrefsWindow />);
    fireEvent.click(screen.getByText("Light")); // theme draft → light
    fireEvent.click(screen.getByText("Save"));

    expect(loadPrefs().theme).toBe("light"); // persisted to fv_prefs
    expect(state.setTheme).toHaveBeenCalledWith("light"); // applied live
    expect(state.setToolsLayout).toHaveBeenCalled();
    expect(state.setPrefsOpen).toHaveBeenCalledWith(false); // closes
  });

  it("renders nothing when closed", () => {
    state.prefsOpen = false;
    const { container } = render(<PrefsWindow />);
    expect(container).toBeEmptyDOMElement();
    state.prefsOpen = true;
  });
});
