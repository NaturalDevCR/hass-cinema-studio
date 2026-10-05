import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePlayer } from "@/composables/usePlayer";
import ClipCard from "./ClipCard.vue";
import { makeClip } from "@/test/factories";

describe("ClipCard", () => {
  it("renders metadata and state badges, and emits open, play and select", async () => {
    const wrapper = mount(ClipCard, { props: { clip: makeClip({ id: "film", render_pending: true, needs_source: true }), selected: false, selecting: false, playing: false } });
    expect(wrapper.text()).toContain("0:12.0");
    expect(wrapper.text()).toContain("−18.0 LUFS");
    expect(wrapper.find('[data-test="pending"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="needs-source"]').exists()).toBe(true);
    await wrapper.get('[data-test="open"]').trigger("click");
    await wrapper.get('[data-test="play"]').trigger("click");
    await wrapper.get('[data-test="select"]').trigger("click");
    expect(wrapper.emitted("open")?.[0]).toEqual(["film"]);
    expect(wrapper.emitted("play")?.[0]).toEqual(["film"]);
    expect(wrapper.emitted("select")?.[0]).toEqual(["film"]);
  });

  describe("long press and inline preview", () => {
    const touch = { pointerType: "touch" } as const;
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); usePlayer().stop(); });

    function card(selecting = false) {
      return mount(ClipCard, { props: { clip: makeClip({ id: "film" }), selected: false, selecting, playing: false } });
    }

    it("selects on a 450 ms press without navigating on the click that follows", async () => {
      const wrapper = card();
      await wrapper.trigger("pointerdown", touch);
      vi.advanceTimersByTime(449);
      expect(wrapper.emitted("select")).toBeUndefined();
      vi.advanceTimersByTime(1);
      expect(wrapper.emitted("select")?.[0]).toEqual(["film"]);
      await wrapper.trigger("pointerup", touch);
      await wrapper.get('[data-test="open"]').trigger("click");
      expect(wrapper.emitted("open")).toBeUndefined();
      await wrapper.get('[data-test="open"]').trigger("click");
      expect(wrapper.emitted("open")?.[0]).toEqual(["film"]);
    });

    it("does not select on a short tap, and the tap still opens", async () => {
      const wrapper = card();
      await wrapper.trigger("pointerdown", touch);
      vi.advanceTimersByTime(200);
      await wrapper.trigger("pointerup", touch);
      vi.advanceTimersByTime(1000);
      await wrapper.get('[data-test="open"]').trigger("click");
      expect(wrapper.emitted("select")).toBeUndefined();
      expect(wrapper.emitted("open")?.[0]).toEqual(["film"]);
    });

    it("clears the swallow flag when the press is cancelled after it fired", async () => {
      const wrapper = card();
      await wrapper.trigger("pointerdown", touch);
      vi.advanceTimersByTime(450);
      await wrapper.trigger("pointercancel", touch);
      await wrapper.get('[data-test="open"]').trigger("click");
      expect(wrapper.emitted("open")?.[0]).toEqual(["film"]);
    });

    it("does not leave a stale swallow flag after a long press whose click never came", async () => {
      const wrapper = card();
      await wrapper.trigger("pointerdown", touch);
      vi.advanceTimersByTime(450);
      await wrapper.trigger("pointerup", touch);
      vi.advanceTimersByTime(1000);
      await wrapper.get('[data-test="open"]').trigger("click");
      expect(wrapper.emitted("open")?.[0]).toEqual(["film"]);
    });

    it("mounts the shared preview video inside the card when play is pressed", async () => {
      vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
      vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
      vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => undefined);
      const wrapper = card();
      expect(wrapper.element.querySelector("video")).toBeNull();
      await wrapper.get('[data-test="play"]').trigger("click");
      const video = wrapper.element.querySelector("video");
      expect(video).toBe(usePlayer().element());
      expect(video?.getAttribute("src")).toContain("film");
      expect(usePlayer().currentId.value).toBe("film");
    });
  });
});
