// Structure modes take the active image as their `id` prop; a request that
// resolves after the prop moves on must not paint the old image's result.

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AtomsResult, CtfResult } from "../../lib/api";

vi.mock("uplot", () => ({
  default: class {
    destroy() {}
  },
}));

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    analyzeAtoms: vi.fn(),
    analyzeCtf: vi.fn(),
  };
});

import { analyzeAtoms, analyzeCtf } from "../../lib/api";
import AtomColumnPanel from "./AtomColumnPanel";
import { CtfMode } from "./structure/CtfStitchModes";

const atoms: AtomsResult = {
  n_columns: 417,
  positions: [[4, 4]],
  amplitude: [1],
  converged: [true],
  lattice: { valid: false, a1: null, a2: null, spacing: null },
};

const ctf: CtfResult = {
  defocus_a: -812,
  defocus_nm: -81.2,
  r_squared: 0.913,
  lambda_a: 0.0251,
  radial_freq: [0, 1],
  radial_power: [1, 0.5],
  ctf_fit: [1, 0.4],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("Structure modes stale responses", () => {
  it("drops atom columns detected on the previous image", async () => {
    const pending = deferred<AtomsResult>();
    vi.mocked(analyzeAtoms).mockReturnValue(pending.promise);
    const view = render(<AtomColumnPanel id="a" />);

    fireEvent.click(screen.getByRole("button", { name: "Detect + Fit" }));
    const signal = vi.mocked(analyzeAtoms).mock.calls[0]![1]!.signal!;
    view.rerender(<AtomColumnPanel id="b" />);
    await act(async () => pending.resolve(atoms));

    expect(signal.aborted).toBe(true);
    expect(screen.queryByText(/417 columns/)).toBeNull();
    expect(screen.getByRole("button", { name: "Detect + Fit" })).not.toBeDisabled();
  });

  it("keeps the newer CTF estimate when an older one resolves late", async () => {
    const first = deferred<CtfResult>();
    vi.mocked(analyzeCtf)
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce({ ...ctf, defocus_nm: -40.5 });
    const view = render(<CtfMode id="a" />);

    fireEvent.click(screen.getByRole("button", { name: "Estimate" }));
    view.rerender(<CtfMode id="b" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Estimate" }));
    });
    expect(screen.getByText(/Δf = -40\.5 nm/)).toBeVisible();

    await act(async () => first.resolve(ctf));
    expect(screen.getByText(/Δf = -40\.5 nm/)).toBeVisible();
    expect(screen.queryByText(/Δf = -81\.2 nm/)).toBeNull();
    expect(screen.getByRole("button", { name: "Estimate" })).not.toBeDisabled();
  });
});
