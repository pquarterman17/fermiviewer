import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { ParamField } from "../../lib/params";
import { askParams, useParamDialog } from "../../store/params";
import ParamDialog from "./ParamDialog";

const num = (key: string, def: number): ParamField => ({
  key,
  label: key,
  type: "number",
  default: def,
});

describe("ParamDialog queue rendering", () => {
  beforeEach(() => {
    useParamDialog.getState().cancelAll();
  });

  it("renders queued requests one at a time, in order", async () => {
    render(<ParamDialog />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    act(() => {
      void askParams("First op", [num("a", 1)]);
      void askParams("Second op", [num("b", 2)]);
    });

    expect(await screen.findByRole("heading", { name: "First op" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Second op" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    // the queued request takes over the same dialog instance
    expect(await screen.findByRole("heading", { name: "Second op" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /run/i }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("resolves each request with the values typed for THAT request", async () => {
    render(<ParamDialog />);
    let first: Promise<unknown> = Promise.resolve();
    let second: Promise<unknown> = Promise.resolve();
    act(() => {
      first = askParams("First op", [num("a", 1)]);
      second = askParams("Second op", [num("b", 2)]);
    });

    await screen.findByRole("heading", { name: "First op" });
    // NB: the field label is a <span>, not a <label for=...>, so the input has
    // no accessible name to query by — hence getByRole over getByLabelText.
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "11" } });
    fireEvent.click(screen.getByRole("button", { name: /run/i }));
    await expect(first).resolves.toEqual({ a: 11 });

    await screen.findByRole("heading", { name: "Second op" });
    // Defaults must be re-seeded for the next request, not carried over.
    expect(screen.getByRole("textbox")).toHaveValue("2");
    fireEvent.click(screen.getByRole("button", { name: /run/i }));
    await expect(second).resolves.toEqual({ b: 2 });
  });

  it("re-seeds defaults even when consecutive requests share a title", async () => {
    // Guards the effect-dependency choice: keying re-initialisation on the
    // title alone would leave the second request showing the first's values.
    render(<ParamDialog />);
    act(() => {
      void askParams("Same title", [num("v", 1)]);
      void askParams("Same title", [num("v", 7)]);
    });

    await screen.findByRole("heading", { name: "Same title" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "99" } });
    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue("7"));
  });

  it("cancelling the active request shows the next instead of closing", async () => {
    render(<ParamDialog />);
    let first: Promise<unknown> = Promise.resolve();
    act(() => {
      first = askParams("First op", [num("a", 1)]);
      void askParams("Second op", [num("b", 2)]);
    });

    await screen.findByRole("heading", { name: "First op" });
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    await expect(first).resolves.toBeNull();
    expect(await screen.findByRole("heading", { name: "Second op" })).toBeInTheDocument();
  });

  it("Escape cancels only the active request", async () => {
    render(<ParamDialog />);
    let first: Promise<unknown> = Promise.resolve();
    act(() => {
      first = askParams("First op", [num("a", 1)]);
      void askParams("Second op", [num("b", 2)]);
    });

    await screen.findByRole("heading", { name: "First op" });
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });

    await expect(first).resolves.toBeNull();
    expect(await screen.findByRole("heading", { name: "Second op" })).toBeInTheDocument();
  });

  it("unmounting does not settle pending requests on its own", async () => {
    // ParamDialog unmounts on every normal close (LazyOverlays drops it when
    // the queue empties) and StrictMode double-invokes mount effects, so an
    // unmount-cancels-everything effect would cancel live requests. Teardown
    // settles the queue explicitly via cancelAll instead.
    const { unmount } = render(<ParamDialog />);
    let pending: Promise<unknown> = Promise.resolve();
    act(() => {
      pending = askParams("Still open", [num("a", 1)]);
    });
    await screen.findByRole("heading", { name: "Still open" });

    unmount();
    expect(useParamDialog.getState().queue).toHaveLength(1);

    act(() => useParamDialog.getState().cancelAll());
    await expect(pending).resolves.toBeNull();
  });
});
