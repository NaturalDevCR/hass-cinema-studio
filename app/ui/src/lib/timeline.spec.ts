import { describe, it, expect } from "vitest";
import { timeToX, xToTime, snapTime, frameIndexForTime } from "./timeline";
describe("original timeline", () => {
  it("round trips and clamps", () => {
    expect(xToTime(timeToX(7, 12, 300), 12, 300)).toBe(7);
    expect(xToTime(-2, 12, 300)).toBe(0);
    expect(xToTime(400, 12, 300)).toBe(12);
    expect(xToTime(1, 12, 0)).toBe(0);
  });
  it("snaps to frames or hundredths", () => {
    expect(snapTime(0.13, 24)).toBe(3 / 24);
    expect(snapTime(0.136, null)).toBe(0.14);
  });
  it("selects bounded original thumbnails", () => {
    expect(frameIndexForTime(5, 2, 4)).toBe(2);
    expect(frameIndexForTime(99, 2, 4)).toBe(3);
  });
});
