// Card (#37) — shared collapsible inspector card. Persistence contract:
// localStorage["fv_cards_v2"] keyed by title; default open.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Card from "./Card";

function getDetails(container: HTMLElement): HTMLDetailsElement {
  const el = container.querySelector("details.fvd-card");
  if (!el) throw new Error("details.fvd-card not rendered");
  return el as HTMLDetailsElement;
}

describe("Card", () => {
  it("renders title + children, open by default", () => {
    const { container } = render(
      <Card title="Adjust">
        <div>histogram</div>
      </Card>,
    );
    expect(screen.getByText("Adjust")).toBeInTheDocument();
    expect(screen.getByText("histogram")).toBeInTheDocument();
    expect(getDetails(container).open).toBe(true);
  });

  it("clicking the summary collapses and persists to fv_cards_v2", () => {
    const { container } = render(
      <Card title="Metadata">
        <div>rows</div>
      </Card>,
    );
    fireEvent.click(screen.getByText("Metadata"));
    expect(getDetails(container).open).toBe(false);
    expect(
      (JSON.parse(localStorage.getItem("fv_cards_v2") ?? "{}") as Record<string, boolean>)[
        "Metadata"
      ],
    ).toBe(false);
    // toggle back
    fireEvent.click(screen.getByText("Metadata"));
    expect(getDetails(container).open).toBe(true);
  });

  it("mounts collapsed when fv_cards_v2 says so (persisted across sessions)", () => {
    localStorage.setItem("fv_cards_v2", JSON.stringify({ EELS: false }));
    const { container } = render(
      <Card title="EELS">
        <div>workshop</div>
      </Card>,
    );
    expect(getDetails(container).open).toBe(false);
  });

  it("respects defaultOpen=false for unseen titles", () => {
    const { container } = render(
      <Card title="Never seen" defaultOpen={false}>
        <div>x</div>
      </Card>,
    );
    expect(getDetails(container).open).toBe(false);
  });

  it("renders a count badge only when count is provided", () => {
    const { container, rerender } = render(
      <Card title="Measurements" count={3}>
        <div>list</div>
      </Card>,
    );
    expect(container.querySelector(".fvd-card-count")?.textContent).toBe("3");
    // zero is a real count — must still render (count != null, not falsy)
    rerender(
      <Card title="Measurements" count={0}>
        <div>list</div>
      </Card>,
    );
    expect(container.querySelector(".fvd-card-count")?.textContent).toBe("0");
    // omitting count drops the badge entirely
    rerender(
      <Card title="Measurements">
        <div>list</div>
      </Card>,
    );
    expect(container.querySelector(".fvd-card-count")).toBeNull();
  });

  it("corrupted fv_cards_v2 falls back to default open", () => {
    localStorage.setItem("fv_cards_v2", "[not a map]");
    const { container } = render(
      <Card title="Image">
        <div>y</div>
      </Card>,
    );
    expect(getDetails(container).open).toBe(true);
  });
});
