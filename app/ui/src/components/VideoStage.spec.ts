import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import VideoStage from "./VideoStage.vue";
import { makeClip } from "@/test/factories";
import type { Recipe } from "@/api/types";

const base = makeClip({ id: "a" });
const recipe = (patch: Partial<Recipe> = {}): Recipe => ({ ...base.recipe, trim_start: 2, trim_end: 10, ...patch });
let wrapper: ReturnType<typeof mount>;
beforeEach(() => {
  vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});
afterEach(() => {
  wrapper?.unmount();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
function mountStage(props: Record<string, unknown> = {}) {
  wrapper = mount(VideoStage, {
    props: {
      clip: base,
      recipe: recipe(),
      source: "original",
      previewVersion: "",
      loop: false,
      fadeIn: 1,
      fadeOut: 2,
      ...props,
    },
  });
  const video = wrapper.get("video").element as HTMLVideoElement;
  const state = { paused: true, seeking: false, currentTime: 0, volume: 1, duration: 12 };
  for (const key of Object.keys(state) as (keyof typeof state)[])
    Object.defineProperty(video, key, {
      configurable: true,
      get: () => state[key],
      set: (value) => {
        (state as Record<string, unknown>)[key] = value;
      },
    });
  return { video, state };
}
const overlay = () => wrapper.get("[data-test=fade-overlay]").attributes("style") ?? "";

it("ramps opacity and volume only while the original is playing", async () => {
  const { video, state } = mountStage();
  state.currentTime = 2.5;
  state.paused = false;
  await wrapper.get("video").trigger("play");
  expect(state.volume).toBeCloseTo(0.5);
  expect(overlay()).toContain("opacity: 0.5");
  state.paused = true;
  await wrapper.get("video").trigger("pause");
  expect(state.volume).toBe(1);
  expect(overlay()).toContain("opacity: 0");
  expect(overlay()).not.toContain("opacity: 0.5");
  void video;
});
it("shows the frame at full strength while paused or seeking", async () => {
  const { state } = mountStage();
  state.currentTime = 2;
  await wrapper.get("video").trigger("timeupdate");
  expect(state.volume).toBe(1);
  expect(overlay()).toContain("opacity: 0");
  state.paused = false;
  state.seeking = true;
  await wrapper.get("video").trigger("timeupdate");
  expect(state.volume).toBe(1);
  expect(overlay()).not.toContain("opacity: 1");
});
it("fades out towards the trim end", async () => {
  const { state } = mountStage();
  state.paused = false;
  state.currentTime = 9;
  await wrapper.get("video").trigger("play");
  expect(state.volume).toBeCloseTo(0.5);
});
it("recomputes the fade when fades or trim change mid-playback", async () => {
  const { state } = mountStage();
  state.paused = false;
  state.currentTime = 2.5;
  await wrapper.get("video").trigger("play");
  expect(state.volume).toBeCloseTo(0.5);
  await wrapper.setProps({ fadeIn: 0.5 });
  expect(state.volume).toBe(1);
  await wrapper.setProps({ recipe: recipe({ trim_start: 2.25 }) });
  expect(state.volume).toBeCloseTo(0.5);
});
it("never fades preview or render playback", async () => {
  const { state } = mountStage({ source: "preview", previewVersion: "j1" });
  state.paused = false;
  state.currentTime = 0.1;
  await wrapper.get("video").trigger("play");
  expect(state.volume).toBe(1);
  expect(overlay()).toContain("opacity: 0");
});
it("pauses at the trim end, or wraps to the start when looping", async () => {
  const { video, state } = mountStage();
  const pause = vi.spyOn(video, "pause").mockImplementation(() => {
    state.paused = true;
  });
  state.paused = false;
  state.currentTime = 10;
  await wrapper.get("video").trigger("timeupdate");
  expect(pause).toHaveBeenCalled();
  state.paused = false;
  await wrapper.setProps({ loop: true });
  state.currentTime = 10.1;
  await wrapper.get("video").trigger("timeupdate");
  expect(state.currentTime).toBe(2);
});
it("starts playback from the trim start when outside the bounds", async () => {
  const { video, state } = mountStage();
  const play = vi.spyOn(video, "play").mockResolvedValue();
  state.currentTime = 11;
  await (wrapper.vm as unknown as { toggle: () => Promise<void> }).toggle();
  expect(state.currentTime).toBe(2);
  expect(play).toHaveBeenCalled();
});
it("jumps to the in and out points", async () => {
  const { state } = mountStage();
  const vm = wrapper.vm as unknown as { jump: (e: "in" | "out") => void };
  vm.jump("out");
  expect(state.currentTime).toBe(10);
  vm.jump("in");
  expect(state.currentTime).toBe(2);
});
it("does not turn the crop on when locking 16:9 without a crop", async () => {
  mountStage();
  await wrapper.get("input[type=checkbox]").setValue(true);
  expect(wrapper.emitted("crop")).toBeUndefined();
});
it("keeps the stage within 70vh at the source aspect", () => {
  mountStage();
  const stage = wrapper.get("[data-test=stage-box]");
  expect(stage.attributes("style")).toContain("aspect-ratio: 1920 / 1080");
  expect(stage.classes()).toContain("max-h-[70vh]");
  expect(wrapper.get("video").classes()).toContain("object-contain");
});
