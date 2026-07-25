import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, analyzeParticles: vi.fn(), fetchData16: vi.fn() };
});

import { analyzeParticles, fetchData16 } from "../../lib/api";
import ParticlesMode from "./ParticlesMode";

afterEach(() => vi.clearAllMocks());

function raster() {
  return {
    w: 2,
    h: 2,
    vmin: 0,
    vmax: 1,
    nFrames: null,
    data: new Uint16Array([0, 1, 2, 3]),
  };
}

describe("ParticlesMode", () => {
  it("forwards the watershed split option to the endpoint", async () => {
    // The menu dialog that owned this option was replaced by this mode; if
    // the toggle stops reaching the API, touching particles silently merge
    // into one blob with no way for the user to separate them.
    vi.mocked(fetchData16).mockResolvedValue(raster());
    vi.mocked(analyzeParticles).mockResolvedValue({
      n_particles: 0,
      threshold: 0.5,
      labels: { id: "labels" } as never,
      particles: [],
      unit: "nm",
    });

    render(<ParticlesMode id="img" />);
    await waitFor(() => expect(fetchData16).toHaveBeenCalledWith("img"));

    fireEvent.click(screen.getByLabelText("Split touching particles"));
    fireEvent.click(screen.getByRole("button", { name: "Count" }));

    await waitFor(() =>
      expect(analyzeParticles).toHaveBeenCalledWith(
        "img",
        expect.objectContaining({ watershed: true, polarity: "bright" }),
      ),
    );
  });

  it("defaults to no splitting so counts match the previous behaviour", async () => {
    vi.mocked(fetchData16).mockResolvedValue(raster());
    vi.mocked(analyzeParticles).mockResolvedValue({
      n_particles: 0,
      threshold: 0.5,
      labels: { id: "labels" } as never,
      particles: [],
      unit: "nm",
    });

    render(<ParticlesMode id="img" />);
    await waitFor(() => expect(fetchData16).toHaveBeenCalledWith("img"));
    fireEvent.click(screen.getByRole("button", { name: "Count" }));

    await waitFor(() =>
      expect(analyzeParticles).toHaveBeenCalledWith(
        "img",
        expect.objectContaining({ watershed: false }),
      ),
    );
  });
});
