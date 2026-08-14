import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { edsSpecies, eelsSpecies } from "../../lib/spectrum/species";
import { useSpecies } from "../../store/species";
import SpeciesChips from "./SpeciesChips";

const IMG = "cube";

afterEach(() => {
  useSpecies.setState({ byImage: {}, selectedByImage: {}, edsSettingsByImage: {} });
});

describe("SpeciesChips", () => {
  it("shows the default empty hint when the image has no species", () => {
    render(<SpeciesChips imageId={IMG} />);
    expect(screen.getByText(/No species yet/)).toBeVisible();
  });

  it("shows a caller-supplied empty hint instead of the default", () => {
    render(<SpeciesChips imageId={IMG} emptyHint="Nothing here yet" />);
    expect(screen.getByText("Nothing here yet")).toBeVisible();
    expect(screen.queryByText(/No species yet/)).toBeNull();
  });

  it("renders one chip per species on that image, and none for other images", () => {
    useSpecies.getState().addSpecies(IMG, edsSpecies("Fe", "K", 6.404));
    useSpecies.getState().addSpecies(IMG, edsSpecies("Si", "K", 1.74));
    useSpecies.getState().addSpecies("other-image", edsSpecies("Cu", "K", 8.048));

    render(<SpeciesChips imageId={IMG} />);
    expect(screen.getByRole("option", { name: "Fe" })).toBeVisible();
    expect(screen.getByRole("option", { name: "Si" })).toBeVisible();
    expect(screen.queryByRole("option", { name: "Cu" })).toBeNull();
  });

  it("clicking a chip selects that species in the store", () => {
    const fe = edsSpecies("Fe", "K", 6.404);
    useSpecies.getState().addSpecies(IMG, fe);

    render(<SpeciesChips imageId={IMG} />);
    fireEvent.click(screen.getByRole("option", { name: "Fe" }));
    expect(useSpecies.getState().selectedByImage[IMG]).toBe(fe.id);
  });

  it("marks the selected chip aria-selected, and no other", () => {
    const fe = edsSpecies("Fe", "K", 6.404);
    const si = edsSpecies("Si", "K", 1.74);
    useSpecies.getState().addSpecies(IMG, fe);
    useSpecies.getState().addSpecies(IMG, si);
    useSpecies.getState().selectSpecies(IMG, fe.id);

    render(<SpeciesChips imageId={IMG} />);
    expect(screen.getByRole("option", { name: "Fe" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("option", { name: "Si" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("shows two species of the same symbol on different transitions as distinct chips", () => {
    // Si K and Si L23 are distinct measurements — mirrors the ElementList
    // contract for the same case.
    useSpecies.getState().addSpecies(IMG, eelsSpecies("Fe", "L2,3", 708));
    useSpecies.getState().addSpecies(IMG, eelsSpecies("Fe", "K", 7112));

    render(<SpeciesChips imageId={IMG} />);
    expect(screen.getAllByRole("option", { name: "Fe" })).toHaveLength(2);
  });
});
