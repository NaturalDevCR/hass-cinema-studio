import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
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
});
