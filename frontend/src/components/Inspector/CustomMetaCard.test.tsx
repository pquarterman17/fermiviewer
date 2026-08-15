// CustomMetaCard: verifies the three foot-hint wordings name the actual
// sidecar file (not the old unhelpful "no file path for a sidecar"), the
// pathless-only Download button, the "How this works" disclosure, and the
// empty-schema example. api + store are mocked (TransformPanel.test.tsx
// pattern); the anchor-click download idiom follows export.test.ts.
//
// Composite sentences are broken across inline <code>/<b> nodes, so most
// assertions read container.textContent directly rather than screen.getByText
// with a regex — a regex TextMatch does a substring test against every
// element's full (nested) textContent, and matches both a wrapping <details>
// and its child in this layout, which throws "multiple elements found".

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { UserMeta } from "../../lib/api";

const state = {
  activeId: "img1" as string | null,
  order: ["img1", "img2"],
  setStatus: vi.fn(),
};

vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign((sel: (s: typeof state) => unknown) => sel(state), {
    getState: () => state,
  }),
}));

const getUserMetaMock = vi.fn();
const saveUserMetaMock = vi.fn();
const batchAutofillMock = vi.fn();
const downloadUserMetaSidecarMock = vi.fn();

vi.mock("../../lib/api", () => ({
  getUserMeta: (...a: unknown[]) => getUserMetaMock(...a),
  saveUserMeta: (...a: unknown[]) => saveUserMetaMock(...a),
  batchAutofill: (...a: unknown[]) => batchAutofillMock(...a),
  downloadUserMetaSidecar: (...a: unknown[]) => downloadUserMetaSidecarMock(...a),
}));

import CustomMetaCard from "./CustomMetaCard";

const FIELD = { name: "Design", type: "text", options: [] as string[] };

function makeInfo(overrides: Partial<UserMeta> = {}): UserMeta {
  return {
    fields: [FIELD],
    patterns: ["D{Design}_L{Lot}_W{Wafer}_R{Reticle}"],
    config_path: "/home/user/.config/fermiviewer/metadata.yaml",
    values: { Design: "1234" },
    source_path: "/data/D1234.dm3",
    can_write_sidecar: true,
    has_sidecar: true,
    sidecar_name: "D1234.dm3.fvmeta.yaml",
    ...overrides,
  };
}

describe("CustomMetaCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.activeId = "img1";
    state.order = ["img1", "img2"];
  });

  it("path + sidecar exists: names the actual file, no Download button", async () => {
    getUserMetaMock.mockResolvedValue(
      makeInfo({ can_write_sidecar: true, has_sidecar: true }),
    );
    const { container } = render(<CustomMetaCard />);
    await screen.findByText("Design");
    expect(container.textContent).toContain(
      "Saved in D1234.dm3.fvmeta.yaml next to the image",
    );
    expect(container.textContent).toContain(
      "load automatically whenever this file is opened",
    );
    expect(screen.queryByText("Download metadata file")).toBeNull();
  });

  it("path, no sidecar yet: names the file Save will write, no Download button", async () => {
    getUserMetaMock.mockResolvedValue(
      makeInfo({ can_write_sidecar: true, has_sidecar: false }),
    );
    const { container } = render(<CustomMetaCard />);
    await screen.findByText("Design");
    expect(container.textContent).toContain(
      "Save writes D1234.dm3.fvmeta.yaml next to the image",
    );
    expect(container.textContent).toContain("load automatically next time");
    expect(screen.queryByText("Download metadata file")).toBeNull();
  });

  it("no path: explains session-only + workspace clause, shows Download button", async () => {
    getUserMetaMock.mockResolvedValue(
      makeInfo({
        can_write_sidecar: false,
        has_sidecar: false,
        source_path: null,
        sidecar_name: "uploaded.dm3.fvmeta.yaml",
      }),
    );
    const { container } = render(<CustomMetaCard />);
    await screen.findByText("Design");
    expect(container.textContent).toContain(
      "didn't come from a file on disk",
    );
    expect(container.textContent).toContain("this session only");
    expect(container.textContent).toContain("Save Project");
    expect(container.textContent).toContain(
      "Download metadata file gives you uploaded.dm3.fvmeta.yaml",
    );
    expect(screen.getByText("Download metadata file")).toBeInTheDocument();
  });

  describe("Download metadata file button", () => {
    beforeEach(() => {
      globalThis.URL.createObjectURL = vi.fn(() => "blob:mock");
      globalThis.URL.revokeObjectURL = vi.fn();
      vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    });
    afterEach(() => vi.restoreAllMocks());

    it("only renders when can_write_sidecar is false", async () => {
      getUserMetaMock.mockResolvedValue(makeInfo({ can_write_sidecar: true }));
      render(<CustomMetaCard />);
      await screen.findByText("Design");
      expect(screen.queryByText("Download metadata file")).toBeNull();
    });

    it("fetches the sidecar bytes and triggers a browser download", async () => {
      getUserMetaMock.mockResolvedValue(
        makeInfo({ can_write_sidecar: false, has_sidecar: false, source_path: null }),
      );
      downloadUserMetaSidecarMock.mockResolvedValue({
        blob: new Blob(["Design: '1234'\n"], { type: "application/x-yaml" }),
        filename: "D1234.dm3.fvmeta.yaml",
      });

      render(<CustomMetaCard />);
      fireEvent.click(await screen.findByText("Download metadata file"));

      await waitFor(() =>
        expect(downloadUserMetaSidecarMock).toHaveBeenCalledWith("img1"),
      );
      await waitFor(() =>
        expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled(),
      );
      expect(state.setStatus).toHaveBeenCalledWith(
        "downloaded D1234.dm3.fvmeta.yaml",
      );
    });

    it("reports the error via setStatus when the download fails", async () => {
      getUserMetaMock.mockResolvedValue(
        makeInfo({ can_write_sidecar: false, has_sidecar: false, source_path: null }),
      );
      downloadUserMetaSidecarMock.mockRejectedValue(new Error("boom"));

      render(<CustomMetaCard />);
      fireEvent.click(await screen.findByText("Download metadata file"));

      await waitFor(() =>
        expect(state.setStatus).toHaveBeenCalledWith("metadata: boom"),
      );
    });
  });

  it("'How this works' is collapsed by default and expands on toggle", async () => {
    getUserMetaMock.mockResolvedValue(makeInfo());
    const { container } = render(<CustomMetaCard />);
    await screen.findByText("Design");

    const details = container.querySelector(
      "details:not(.fvd-card)",
    ) as HTMLDetailsElement;
    expect(details).toBeTruthy();
    expect(details.open).toBe(false);

    fireEvent.click(screen.getByText("How this works"));
    expect(details.open).toBe(true);

    // starter example + config path: single-node exact text
    expect(
      screen.getByText("/home/user/.config/fermiviewer/metadata.yaml"),
    ).toBeInTheDocument();
    expect(screen.getByText("D1234_L44576_W1234_R13.dm3")).toBeInTheDocument();
    // composite sentences span inline <code>/<b> nodes — check the raw text
    expect(container.textContent).toContain(
      "Fields are configured in",
    );
    expect(container.textContent).toContain(
      "into Design=1234, Lot=44576, Wafer=1234, Reticle=13",
    );
    expect(container.textContent).toContain(
      "Values resolve filename auto-fill first",
    );
    expect(container.textContent).toContain(
      "stores the values above for this image",
    );
    expect(container.textContent).toContain(
      "runs the filename pattern on every open image and saves each one",
    );
  });

  it("empty-schema state shows a copy-pasteable fields: example + pattern note + config path", async () => {
    getUserMetaMock.mockResolvedValue(makeInfo({ fields: [] }));
    const { container } = render(<CustomMetaCard />);
    expect(await screen.findByText("No fields configured")).toBeInTheDocument();

    const pre = container.querySelector("pre");
    expect(pre?.textContent).toBe("fields:\n  - Design\n  - Lot\n  - Wafer");

    expect(container.textContent).toContain("pattern:");
    expect(container.textContent).toContain("D{Design}_L{Lot}");
    expect(container.textContent).toContain(
      "fill fields from the file name automatically",
    );
    expect(
      screen.getByText("/home/user/.config/fermiviewer/metadata.yaml"),
    ).toBeInTheDocument();
  });

  it("renders nothing when no active image", () => {
    state.activeId = null;
    getUserMetaMock.mockResolvedValue(makeInfo());
    const { container } = render(<CustomMetaCard />);
    expect(container.firstChild).toBeNull();
  });

  it("a same-image refresh in flight (e.g. Auto-fill all) must not clobber an edit typed while it was loading — the dirty guard has to see the LIVE dirty flag, not the one from when the refetch started", async () => {
    getUserMetaMock.mockResolvedValueOnce(
      makeInfo({ values: { Design: "1234" } }),
    );
    let resolveReload!: (u: UserMeta) => void;
    const reloadFetch = new Promise<UserMeta>((resolve) => {
      resolveReload = resolve;
    });
    getUserMetaMock.mockImplementationOnce(() => reloadFetch);
    batchAutofillMock.mockResolvedValue({ n_matched: 1, n_total: 2 });

    render(<CustomMetaCard />);
    await screen.findByText("Design");

    // Kick off a same-image refresh (Auto-fill all → batchAutofill →
    // setReload → the effect refetches getUserMeta for the active image).
    fireEvent.click(screen.getByRole("button", { name: /Auto-fill all/ }));
    await waitFor(() => expect(getUserMetaMock).toHaveBeenCalledTimes(2));

    // While that refetch is still in flight, the user edits the field —
    // dirty flips true AFTER the effect's closure was already created.
    const input = screen.getByDisplayValue("1234");
    fireEvent.change(input, { target: { value: "9999" } });
    expect(input).toHaveValue("9999");

    // The refetch resolves with the server's (older) value. Because the
    // user is dirty right now, it must not overwrite the in-progress edit.
    await act(async () => {
      resolveReload(makeInfo({ values: { Design: "1234" } }));
      await reloadFetch;
    });

    expect(input).toHaveValue("9999");
  });
});
