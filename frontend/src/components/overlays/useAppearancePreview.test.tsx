// The appearance preview mutates GLOBAL document state from inside a dialog,
// so the paths that matter are the ones that ESCAPE the dialog: unmount, and
// commit-then-unmount. PrefsWindow.test.tsx mocks setPrefsOpen with a bare
// vi.fn(), so prefsOpen never flips and the component never unmounts — it can
// only reach cancel(). These drive the hook directly to cover the rest.

import { render } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { DEFAULTS, savePrefs, type Prefs } from "../../lib/prefs";
import { useAppearancePreview } from "./useAppearancePreview";

const look = () => ({
  theme: document.documentElement.getAttribute("data-theme"),
  accent: document.documentElement.getAttribute("data-accent"),
});

let api: ReturnType<typeof useAppearancePreview>;

function Harness({ open }: { open: boolean }) {
  const [prefs, setPrefs] = useState<Prefs>(DEFAULTS);
  api = useAppearancePreview(open, () => undefined, prefs, setPrefs);
  return null;
}

beforeEach(() => {
  localStorage.clear();
  savePrefs({ ...DEFAULTS, theme: "dark", accent: "violet" });
  document.documentElement.setAttribute("data-theme", "dark");
  document.documentElement.setAttribute("data-accent", "violet");
});

describe("useAppearancePreview", () => {
  it("applies a preview without persisting it", () => {
    render(<Harness open />);
    api.preview("accent", "rose");
    expect(look().accent).toBe("rose");
    // the saved prefs must be untouched until commit
    expect(
      (JSON.parse(localStorage.getItem("fv_prefs") ?? "{}") as Prefs).accent,
    ).toBe("violet");
  });

  it("restores the saved appearance when the dialog unmounts", () => {
    const { unmount } = render(<Harness open />);
    api.preview("accent", "rose");
    expect(look().accent).toBe("rose");
    unmount();
    expect(look().accent).toBe("violet");
  });

  it("does NOT revert a committed change when the dialog then unmounts", () => {
    // The classic failure in this pattern: Save persists, the dialog closes,
    // and the unmount cleanup helpfully undoes what was just saved.
    const { unmount } = render(<Harness open />);
    api.preview("accent", "rose");
    api.commit();
    unmount();
    expect(look().accent).toBe("rose");
  });

  it("re-captures the saved value on reopen rather than a stale one", () => {
    const first = render(<Harness open />);
    api.preview("accent", "rose");
    api.commit();
    savePrefs({ ...DEFAULTS, theme: "dark", accent: "rose" });
    first.unmount();

    // Reopening must treat rose as the baseline, so cancelling a further
    // preview returns to rose — not to the violet from the first session.
    const second = render(<Harness open />);
    api.preview("accent", "teal");
    expect(look().accent).toBe("teal");
    second.unmount();
    expect(look().accent).toBe("rose");
  });
});
