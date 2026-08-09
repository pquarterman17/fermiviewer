import { beforeEach, describe, expect, it } from "vitest";

import { useBrowseScale } from "./browseScale";

const reset = () => useBrowseScale.setState({ locked: false, scale: null });

describe("browseScale store", () => {
  beforeEach(reset);

  it("starts disabled with no seeded scale", () => {
    const s = useBrowseScale.getState();
    expect(s.locked).toBe(false);
    expect(s.scale).toBeNull();
  });

  it("enable turns the lock on and seeds the scale", () => {
    useBrowseScale.getState().enable(2.5);
    expect(useBrowseScale.getState()).toMatchObject({
      locked: true,
      scale: 2.5,
    });
  });

  it("reseed updates the scale without turning the lock on", () => {
    useBrowseScale.getState().reseed(4);
    expect(useBrowseScale.getState()).toMatchObject({
      locked: false,
      scale: 4,
    });
  });

  it("reseed updates the scale while already locked", () => {
    useBrowseScale.getState().enable(1);
    useBrowseScale.getState().reseed(9);
    expect(useBrowseScale.getState()).toMatchObject({
      locked: true,
      scale: 9,
    });
  });

  it("clear resets to the default disabled state", () => {
    useBrowseScale.getState().enable(3);
    useBrowseScale.getState().clear();
    expect(useBrowseScale.getState()).toMatchObject({
      locked: false,
      scale: null,
    });
  });

  it("enable is idempotent when called repeatedly with different values", () => {
    useBrowseScale.getState().enable(1);
    useBrowseScale.getState().enable(2);
    expect(useBrowseScale.getState()).toMatchObject({
      locked: true,
      scale: 2,
    });
  });
});
