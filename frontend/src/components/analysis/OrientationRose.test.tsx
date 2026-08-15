// SHAPE_ANALYSIS_PLAN.md item 3: half-rose is AXIAL (never mirrored into
// a full circle) and excludes near-circular particles (eccentricity <
// 0.2) from binning, counting them separately instead.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import OrientationRose, { binOrientations, type OrientedParticle } from "./OrientationRose";

const deg = (d: number) => (d * Math.PI) / 180;

describe("binOrientations", () => {
  it("puts a +80° particle and a −80° particle in DIFFERENT bins (axial, never mirrored)", () => {
    const result = binOrientations([
      { orientation_rad: deg(80), eccentricity: 0.9 },
      { orientation_rad: deg(-80), eccentricity: 0.9 },
    ]);
    const nonEmpty = result.bins.filter((b) => b.count > 0);
    expect(nonEmpty).toHaveLength(2);
    expect(nonEmpty[0].angleDeg).not.toBe(nonEmpty[1].angleDeg);
    // and specifically opposite ends of the half-rose, not folded together
    expect(Math.sign(nonEmpty[0].angleDeg)).not.toBe(Math.sign(nonEmpty[1].angleDeg));
    expect(result.n).toBe(2);
    expect(result.excluded).toBe(0);
  });

  it("spans exactly 18 bins covering (-90°, 90°]", () => {
    const result = binOrientations([]);
    expect(result.bins).toHaveLength(18);
    expect(result.bins[0].angleDeg).toBeCloseTo(-85, 5);
    expect(result.bins[17].angleDeg).toBeCloseTo(85, 5);
  });

  it("excludes near-circular particles (eccentricity < 0.2) from binning", () => {
    const particles: OrientedParticle[] = [
      { orientation_rad: deg(10), eccentricity: 0.1 }, // near-circular: excluded
      { orientation_rad: deg(10), eccentricity: 0.19 }, // still under 0.2: excluded
      { orientation_rad: deg(10), eccentricity: 0.2 }, // exactly 0.2: INCLUDED
      { orientation_rad: deg(10), eccentricity: 0.5 }, // included
    ];
    const result = binOrientations(particles);
    expect(result.excluded).toBe(2);
    expect(result.n).toBe(2);
    const total = result.bins.reduce((sum, b) => sum + b.count, 0);
    expect(total).toBe(2);
  });

  it("assigns a particle at exactly +90° to the last bin (range is inclusive of +90)", () => {
    const result = binOrientations([{ orientation_rad: deg(90), eccentricity: 0.9 }]);
    expect(result.bins[17].count).toBe(1);
  });
});

describe("OrientationRose", () => {
  it("renders the included/excluded counts", () => {
    const particles: OrientedParticle[] = [
      { orientation_rad: deg(30), eccentricity: 0.6 },
      { orientation_rad: deg(-30), eccentricity: 0.7 },
      { orientation_rad: deg(0), eccentricity: 0.05 }, // near-circular
    ];
    render(<OrientationRose particles={particles} />);
    expect(screen.getByText(/N=2/)).toBeInTheDocument();
    expect(screen.getByText(/1 near-circular excluded/)).toBeInTheDocument();
  });

  it("renders nothing extra for an all-included population", () => {
    render(
      <OrientationRose
        particles={[{ orientation_rad: deg(5), eccentricity: 0.6 }]}
      />,
    );
    expect(screen.getByText("N=1")).toBeInTheDocument();
    expect(screen.queryByText(/near-circular excluded/)).not.toBeInTheDocument();
  });
});
