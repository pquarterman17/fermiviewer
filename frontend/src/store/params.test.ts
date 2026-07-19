import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ParamField } from "../lib/params";
import { askParams, useParamDialog } from "./params";

const field = (key: string): ParamField => ({
  key,
  label: key,
  type: "number",
  default: 1,
});

/** Title of the request currently on screen. */
const activeTitle = () => useParamDialog.getState().queue[0]?.title ?? null;

describe("param dialog queue", () => {
  beforeEach(() => {
    useParamDialog.getState().cancelAll();
  });

  it("shows one dialog at a time and queues the rest in FIFO order", () => {
    void askParams("first", [field("a")]);
    void askParams("second", [field("b")]);
    void askParams("third", [field("c")]);

    expect(useParamDialog.getState().queue).toHaveLength(3);
    expect(activeTitle()).toBe("first");

    useParamDialog.getState().submit({ a: 1 });
    expect(activeTitle()).toBe("second");

    useParamDialog.getState().submit({ b: 2 });
    expect(activeTitle()).toBe("third");
  });

  it("settles overlapping callers in order instead of orphaning the first", async () => {
    // The regression: `open` used to overwrite the stored resolver, so the
    // first promise never settled and its caller hung forever.
    const settled: string[] = [];
    const first = askParams("first", [field("a")]).then((v) => {
      settled.push(`first:${JSON.stringify(v)}`);
      return v;
    });
    const second = askParams("second", [field("b")]).then((v) => {
      settled.push(`second:${JSON.stringify(v)}`);
      return v;
    });

    useParamDialog.getState().submit({ a: 10 });
    useParamDialog.getState().submit({ b: 20 });

    await expect(first).resolves.toEqual({ a: 10 });
    await expect(second).resolves.toEqual({ b: 20 });
    // Order matters: the first request must settle first, with its OWN values.
    expect(settled).toEqual(['first:{"a":10}', 'second:{"b":20}']);
  });

  it("cancelling the active request advances to the next one", async () => {
    const first = askParams("first", [field("a")]);
    const second = askParams("second", [field("b")]);

    useParamDialog.getState().close();

    await expect(first).resolves.toBeNull();
    // Cancelling one request must not cancel the queue behind it.
    expect(activeTitle()).toBe("second");
    expect(useParamDialog.getState().queue).toHaveLength(1);

    useParamDialog.getState().submit({ b: 5 });
    await expect(second).resolves.toEqual({ b: 5 });
  });

  it("supports nested asks: a resolved caller can queue another request", async () => {
    // BatchDialog -> addStep awaits askParams, then the batch run asks again.
    // The second ask must land behind anything already queued, not jump ahead.
    const outer = askParams("batch step", [field("kind")]);
    void askParams("unrelated menu action", [field("z")]);

    useParamDialog.getState().submit({ kind: 3 });
    await expect(outer).resolves.toEqual({ kind: 3 });

    const nested = askParams("step parameters", [field("sigma")]);
    // the unrelated request queued first still gets its turn first
    expect(activeTitle()).toBe("unrelated menu action");
    useParamDialog.getState().submit({ z: 0 });

    expect(activeTitle()).toBe("step parameters");
    useParamDialog.getState().submit({ sigma: 2 });
    await expect(nested).resolves.toEqual({ sigma: 2 });
    expect(useParamDialog.getState().queue).toHaveLength(0);
  });

  it("cancelAll settles every pending request with null (teardown)", async () => {
    const a = askParams("a", [field("a")]);
    const b = askParams("b", [field("b")]);
    const c = askParams("c", [field("c")]);

    useParamDialog.getState().cancelAll();

    await expect(a).resolves.toBeNull();
    await expect(b).resolves.toBeNull();
    await expect(c).resolves.toBeNull();
    expect(useParamDialog.getState().queue).toHaveLength(0);
  });

  it("drops resolvers once settled and never calls one twice", async () => {
    const resolve = vi.fn();
    useParamDialog.getState().open("once", [field("a")], resolve);

    useParamDialog.getState().submit({ a: 1 });
    expect(resolve).toHaveBeenCalledTimes(1);
    expect(resolve).toHaveBeenCalledWith({ a: 1 });

    // No retained reference: further settling is a no-op, not a second call.
    useParamDialog.getState().submit({ a: 2 });
    useParamDialog.getState().close();
    useParamDialog.getState().cancelAll();
    expect(resolve).toHaveBeenCalledTimes(1);
    expect(useParamDialog.getState().queue).toHaveLength(0);
  });

  it("submitting with an empty queue is a no-op", () => {
    expect(() => useParamDialog.getState().submit({ a: 1 })).not.toThrow();
    expect(() => useParamDialog.getState().close()).not.toThrow();
    expect(useParamDialog.getState().queue).toHaveLength(0);
  });
});
