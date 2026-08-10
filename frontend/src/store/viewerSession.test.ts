// Browse-scale lock persistence (PROJECT_WORKFLOW_PLAN item 11).
//
// `browseScale` lives in its own standalone store (store/browseScale.ts),
// never on ViewerState — so clientState()/restoreBrowseScale() are the only
// two places that read/write it for a save or load, and are tested directly
// here rather than through the full store round trip.

import { beforeEach, describe, expect, it } from "vitest";

import type { SessionClientState } from "../lib/api";
import { useBrowseScale } from "./browseScale";
import { clientState, restoreBrowseScale } from "./viewerSession";
import { useViewer } from "./viewer";

const resetLock = () => useBrowseScale.setState({ locked: false, scale: null });

describe("clientState — browseScale (item 11)", () => {
  beforeEach(resetLock);

  it("carries the lock off by default", () => {
    expect(clientState(useViewer.getState()).browseScale).toEqual({
      locked: false,
      scale: null,
    });
  });

  it("carries the current locked scale", () => {
    useBrowseScale.getState().enable(2.5);
    expect(clientState(useViewer.getState()).browseScale).toEqual({
      locked: true,
      scale: 2.5,
    });
  });
});

describe("restoreBrowseScale (item 11)", () => {
  beforeEach(resetLock);

  it("restores a locked scale from a saved session", () => {
    restoreBrowseScale({ browseScale: { locked: true, scale: 1.5 } });
    expect(useBrowseScale.getState()).toMatchObject({ locked: true, scale: 1.5 });
  });

  it("restores the off state verbatim", () => {
    useBrowseScale.getState().enable(9);
    restoreBrowseScale({ browseScale: { locked: false, scale: null } });
    expect(useBrowseScale.getState()).toMatchObject({ locked: false, scale: null });
  });

  it("is additive: a pre-#11 project with no browseScale key loads with the lock off", () => {
    useBrowseScale.getState().enable(4); // simulate a lock left on from a prior session
    const preExtension: SessionClientState = { order: ["a"], activeId: "a" };
    restoreBrowseScale(preExtension);
    expect(useBrowseScale.getState()).toMatchObject({ locked: false, scale: null });
  });

  it("is additive: a null client_state (no session at all) turns the lock off", () => {
    useBrowseScale.getState().enable(4);
    restoreBrowseScale(null);
    expect(useBrowseScale.getState()).toMatchObject({ locked: false, scale: null });
  });

  it("never restores a non-finite or non-positive scale", () => {
    restoreBrowseScale({
      browseScale: { locked: true, scale: Number.NaN },
    } as SessionClientState);
    expect(useBrowseScale.getState()).toMatchObject({ locked: false, scale: null });

    restoreBrowseScale({
      browseScale: { locked: true, scale: -1 },
    } as SessionClientState);
    expect(useBrowseScale.getState()).toMatchObject({ locked: false, scale: null });
  });

  it("ignores a locked:true with no usable scale rather than enabling a null lock", () => {
    restoreBrowseScale({
      browseScale: { locked: true, scale: null },
    } as SessionClientState);
    expect(useBrowseScale.getState()).toMatchObject({ locked: false, scale: null });
  });
});
