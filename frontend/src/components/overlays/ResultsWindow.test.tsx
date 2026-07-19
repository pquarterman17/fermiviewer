import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import ResultsWindow, { RESULTS_PAGE_SIZE, useResults } from "./ResultsWindow";

afterEach(() => useResults.getState().close());

describe("ResultsWindow pagination", () => {
  it("renders a bounded page while retaining the full row count", () => {
    useResults.getState().show({
      title: "Many grains",
      columns: ["id", "area"],
      rows: Array.from({ length: 250 }, (_, index) => [index + 1, index * 10]),
    });
    render(<ResultsWindow />);

    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(RESULTS_PAGE_SIZE + 1);
    expect(screen.getByText("250 rows · showing 1–100")).toBeInTheDocument();
    expect(within(table).getByText("1")).toBeInTheDocument();
    expect(within(table).queryByText("101")).toBeNull();

    fireEvent.click(screen.getByText("Next"));
    expect(screen.getByText("250 rows · showing 101–200")).toBeInTheDocument();
    expect(within(table).getByText("101")).toBeInTheDocument();
    expect(within(table).queryByText("1")).toBeNull();
  });

  it("reports an empty table without an inverted range", () => {
    useResults.getState().show({ title: "Empty", columns: ["id"], rows: [] });
    render(<ResultsWindow />);
    expect(screen.getByText("0 rows · showing 0–0")).toBeInTheDocument();
  });
});
