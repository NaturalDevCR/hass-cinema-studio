import { describe, it, expect } from "vitest";
import {
  clampCrop,
  cropFromDisplay,
  displayFromCrop,
  aspectLock,
} from "./crop";
describe("source pixel crop", () => {
  it("bounds, minimum and even pixels", () => {
    const r = clampCrop({ x: 1919, y: -3, w: 17, h: 93 }, 1920, 1080);
    expect(r).toEqual({ x: 1856, y: 0, w: 64, h: 94 });
  });
  it("round trips display coordinates within two source pixels", () => {
    const r = { x: 122, y: 42, w: 800, h: 600 };
    const next = cropFromDisplay(
      displayFromCrop(r, 637, 358, 1920, 1080),
      637,
      358,
      1920,
      1080,
    );
    for (const key of ["x", "y", "w", "h"] as const)
      expect(Math.abs(next[key] - r[key])).toBeLessThanOrEqual(2);
  });
  it("locks aspect preserving the opposite corner", () => {
    expect(aspectLock({ x: 10, y: 20, w: 160, h: 100 }, 16 / 9, "nw")).toEqual({
      x: 10,
      y: 30,
      w: 160,
      h: 90,
    });
  });
});
