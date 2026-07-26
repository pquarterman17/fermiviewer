import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { ImageMeta } from "../../lib/api";
import SpectralModalityPrompt from "./SpectralModalityPrompt";

const meta: ImageMeta = {
  id: "cube",
  name: "ambiguous.ser",
  kind: "spectrum_image",
  shape: [16, 16, 1024],
  dtype: "float32",
  pixel_size: 1,
  pixel_unit: "nm",
  value_unit: "counts",
  n_channels: 1024,
  energy_first: 0,
  energy_last: 2000,
  energy_units: "eV",
  stage_tilt_deg: null,
  meta: {},
};

it("explains an ambiguous cube and returns the selected workflow", () => {
  const choose = vi.fn();
  render(
    <SpectralModalityPrompt
      meta={meta}
      onChoose={choose}
      onClose={() => {}}
    />,
  );
  expect(
    screen.getByRole("dialog", { name: "Choose spectrum workflow" }),
  ).toBeVisible();
  expect(screen.getByText(/0\.000–2000 eV/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /Use EELS/ }));
  expect(choose).toHaveBeenCalledWith("eels");
});
