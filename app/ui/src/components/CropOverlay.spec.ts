import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CropOverlay from "./CropOverlay.vue";

let wrapper: ReturnType<typeof mount>;
beforeEach(() => {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0, y: 0, left: 0, top: 0, right: 480, bottom: 270, width: 480, height: 270, toJSON: () => ({}),
  });
  Element.prototype.setPointerCapture = vi.fn();
});
afterEach(() => {
  wrapper?.unmount();
  vi.restoreAllMocks();
});
function mountOverlay(props: Record<string, unknown> = {}) {
  wrapper = mount(CropOverlay, {
    props: { modelValue: { x: 480, y: 270, w: 960, h: 540 }, width: 1920, height: 1080, locked: false, ...props },
  });
}
const last = () => wrapper.emitted("update:modelValue")!.at(-1)![0];
const box = () => wrapper.get("[data-test=crop-box]");

it("positions the box in percent of the displayed frame", () => {
  mountOverlay();
  const style = box().attributes("style")!;
  expect(style).toContain("left: 25%");
  expect(style).toContain("top: 25%");
  expect(style).toContain("width: 50%");
  expect(style).toContain("height: 50%");
});
it("dims the area outside the crop box", () => {
  mountOverlay();
  expect(wrapper.findAll("[data-test=crop-dim]")).toHaveLength(4);
});
it("moves by the display delta converted to source pixels", async () => {
  mountOverlay();
  await box().trigger("pointerdown", { pointerId: 1, clientX: 100, clientY: 100 });
  await wrapper.trigger("pointermove", { pointerId: 1, clientX: 140, clientY: 120 });
  // 40 display px = 160 source px (x4 scale on both axes).
  expect(last()).toEqual({ x: 640, y: 350, w: 960, h: 540 });
});
it("clamps a move at the frame edge", async () => {
  mountOverlay();
  await box().trigger("pointerdown", { pointerId: 1, clientX: 0, clientY: 0 });
  await wrapper.trigger("pointermove", { pointerId: 1, clientX: 5000, clientY: -5000 });
  expect(last()).toEqual({ x: 960, y: 0, w: 960, h: 540 });
});
it("resizes from the south-east handle with the opposite corner fixed", async () => {
  mountOverlay();
  await wrapper.get('[aria-label="Crop se"]').trigger("pointerdown", { pointerId: 1, clientX: 0, clientY: 0 });
  await wrapper.trigger("pointermove", { pointerId: 1, clientX: 20, clientY: 10 });
  expect(last()).toEqual({ x: 480, y: 270, w: 1040, h: 580 });
});
it("resizes from the north-west handle keeping the far corner", async () => {
  mountOverlay();
  await wrapper.get('[aria-label="Crop nw"]').trigger("pointerdown", { pointerId: 1, clientX: 0, clientY: 0 });
  await wrapper.trigger("pointermove", { pointerId: 1, clientX: -20, clientY: -10 });
  expect(last()).toEqual({ x: 400, y: 230, w: 1040, h: 580 });
});
it("keeps 16:9 while resizing a locked crop", async () => {
  mountOverlay({ locked: true });
  await wrapper.get('[aria-label="Crop se"]').trigger("pointerdown", { pointerId: 1, clientX: 0, clientY: 0 });
  await wrapper.trigger("pointermove", { pointerId: 1, clientX: 40, clientY: 0 });
  const r = last() as { w: number; h: number };
  expect(r.w).toBe(1120);
  expect(r.h).toBe(630);
});
it("stops resizing after the pointer is released", async () => {
  mountOverlay();
  await box().trigger("pointerdown", { pointerId: 1, clientX: 0, clientY: 0 });
  await wrapper.trigger("pointerup", { pointerId: 1 });
  await wrapper.trigger("pointermove", { pointerId: 1, clientX: 40, clientY: 40 });
  expect(wrapper.emitted("update:modelValue")).toBeUndefined();
});
it("ignores moves from another pointer", async () => {
  mountOverlay();
  await box().trigger("pointerdown", { pointerId: 1, clientX: 0, clientY: 0 });
  await wrapper.trigger("pointermove", { pointerId: 2, clientX: 40, clientY: 40 });
  expect(wrapper.emitted("update:modelValue")).toBeUndefined();
});
