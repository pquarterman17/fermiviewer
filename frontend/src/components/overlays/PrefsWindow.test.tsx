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
  setAccent: vi.fn(),
  setDensity: vi.fn(),
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
    document.documentElement.setAttribute("data-theme", "dark");
    document.documentElement.setAttribute("data-accent", "violet");
    document.documentElement.setAttribute("data-density", "regular");
  });

  it("renders the 4-section nav and the Appearance pane by default", () => {
    render(<PrefsWindow />);
    expect(screen.getByText("Preferences")).toBeInTheDocument();
    expect(screen.getByText("Appearance")).toBeInTheDocument();
    expect(screen.getByText("Export")).toBeInTheDocument();
    // the "Advanced" junk-drawer section was dropped in the regroup
    expect(screen.queryByText("Advanced")).toBeNull();
    // Appearance content — incl. the colorbar settings moved out of Advanced
    expect(screen.getByText("Theme")).toBeInTheDocument();
    expect(screen.getByText("Colorbar side")).toBeInTheDocument();
    // Export content is not mounted until that section is selected
    expect(screen.queryByText("Bake scale bar by default")).toBeNull();
  });

  it("switches sections via the left nav", () => {
    render(<PrefsWindow />);
    fireEvent.click(screen.getByText("Export"));
    expect(screen.getByText("Bake scale bar by default")).toBeInTheDocument();
    expect(screen.queryByText("Theme")).toBeNull();
  });

  it("regroup: fixed-zoom moved to Tools & Layout, tilt to Measurement", () => {
    render(<PrefsWindow />);
    fireEvent.click(screen.getByText("Tools & Layout"));
    expect(screen.getByText("Fixed-zoom size (px)")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Measurement"));
    expect(screen.getByText("Default tilt geometry")).toBeInTheDocument();
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

  it("Save applies the chosen accent scheme + density live and persists", () => {
    render(<PrefsWindow />);
    fireEvent.click(screen.getByLabelText("Teal")); // accent draft → teal
    fireEvent.click(screen.getByText("Compact")); // density draft → compact
    fireEvent.click(screen.getByText("Save"));

    expect(loadPrefs().accent).toBe("teal");
    expect(loadPrefs().density).toBe("compact");
    expect(state.setAccent).toHaveBeenCalledWith("teal");
    expect(state.setDensity).toHaveBeenCalledWith("compact");
  });

  it("previews appearance immediately and Cancel restores the saved appearance", () => {
    render(<PrefsWindow />);
    fireEvent.click(screen.getByText("Light"));
    fireEvent.click(screen.getByLabelText("Rose"));
    fireEvent.click(screen.getByText("Compact"));

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(document.documentElement).toHaveAttribute("data-accent", "rose");
    expect(document.documentElement).toHaveAttribute("data-density", "compact");
    expect(loadPrefs().theme).toBe("system");
    expect(state.setTheme).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Cancel"));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(document.documentElement).toHaveAttribute("data-accent", "violet");
    expect(document.documentElement).toHaveAttribute("data-density", "regular");
    expect(state.setPrefsOpen).toHaveBeenCalledWith(false);
  });

  it("renders nothing when closed", () => {
    state.prefsOpen = false;
    const { container } = render(<PrefsWindow />);
    expect(container).toBeEmptyDOMElement();
    state.prefsOpen = true;
  });
});
