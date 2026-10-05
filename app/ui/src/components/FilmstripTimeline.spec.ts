import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import FilmstripTimeline from "./FilmstripTimeline.vue";
import { makeClip } from "@/test/factories";
import type { Recipe } from "@/api/types";

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  api: vi.fn().mockResolvedValue({ interval: 2, count: 0, width: 160, height: 90 }),
}));
const base = makeClip({ id: "a" });
const recipe = (patch: Partial<Recipe> = {}): Recipe => ({ ...base.recipe, trim_start: 3, trim_end: 9, ...patch });
let wrapper: ReturnType<typeof mount>;
beforeEach(() => {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0, y: 0, left: 0, top: 0, right: 1200, bottom: 96, width: 1200, height: 96, toJSON: () => ({}),
  });
  Element.prototype.setPointerCapture = vi.fn();
});
afterEach(() => {
  wrapper?.unmount();
  vi.restoreAllMocks();
});
async function mountTimeline(patch: Partial<Recipe> = {}) {
  wrapper = mount(FilmstripTimeline, {
    props: { clipId: "a", duration: 12, fps: 24, recipe: recipe(patch), position: 0 },
  });
  await flushPromises();
}
const strip = () => wrapper.get("[data-test=strip]");
const handle = (edge: "Start" | "End") => wrapper.get(`[role=slider][aria-label="Trim ${edge.toLowerCase()}"]`);

it("seeks on click, snapped to the frame grid", async () => {
  await mountTimeline();
  await strip().trigger("pointerdown", { pointerId: 1, clientX: 600 });
  expect(wrapper.emitted("seek")![0]).toEqual([6]);
  await strip().trigger("pointerdown", { pointerId: 1, clientX: 1210 });
  expect(wrapper.emitted("seek")![1]).toEqual([12]);
});
it("drags the start handle without seeking", async () => {
  await mountTimeline();
  await handle("Start").trigger("pointerdown", { pointerId: 1, clientX: 300 });
  await strip().trigger("pointermove", { pointerId: 1, clientX: 400 });
  expect(wrapper.emitted("trim")!.at(-1)).toEqual([4, 9]);
  expect(wrapper.emitted("seek")).toBeUndefined();
  await strip().trigger("pointerup", { pointerId: 1 });
  await strip().trigger("pointermove", { pointerId: 1, clientX: 800 });
  expect(wrapper.emitted("trim")).toHaveLength(1);
});
it("drags the end handle to the full duration as an open end", async () => {
  await mountTimeline();
  await handle("End").trigger("pointerdown", { pointerId: 1, clientX: 900 });
  await strip().trigger("pointermove", { pointerId: 1, clientX: 5000 });
  expect(wrapper.emitted("trim")!.at(-1)).toEqual([3, null]);
});
it("aligns the trim region and margins with the handles", async () => {
  await mountTimeline({ lead_in: 1.2, tail_out: 2.4 });
  const left = (el: string) => parseFloat(wrapper.get(el).attributes("style")!.match(/left: ([\d.]+)%/)![1]!);
  const width = (el: string) => parseFloat(wrapper.get(el).attributes("style")!.match(/width: ([\d.]+)%/)![1]!);
  expect(left("[data-test=trim-region]")).toBeCloseTo(25);
  expect(width("[data-test=trim-region]")).toBeCloseTo(50);
  expect(handle("Start").attributes("style")).toContain("left: 25%");
  expect(handle("End").attributes("style")).toContain("left: 75%");
  // Margins hug the trim region on the same time scale (1.2 s of 12 s = 10%).
  expect(left("[data-test=lead-block]") + width("[data-test=lead-block]")).toBeCloseTo(25);
  expect(width("[data-test=lead-block]")).toBeCloseTo(10);
  expect(left("[data-test=tail-block]")).toBeCloseTo(75);
  expect(width("[data-test=tail-block]")).toBeCloseTo(20);
});
it("rolls the margin blocks back inside the bar at the clip edges", async () => {
  await mountTimeline({ trim_start: 0, trim_end: null, lead_in: 3 });
  const lead = wrapper.get("[data-test=lead-block]").attributes("style")!;
  expect(lead).toContain("left: 0%");
  expect(lead).toContain("width: 0%");
});
