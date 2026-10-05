import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeState } from "@/test/system";
import TestTargets from "./TestTargets.vue";

const save = vi.fn();
vi.mock("@/composables/useSettingsSave", () => ({
  useSettingsSave: () => ({ pending: { value: false }, error: { value: null }, save }),
}));

describe("TestTargets", () => {
  beforeEach(() => save.mockReset());

  it("rejects non-media-player and protected entities with explanations", async () => {
    const wrapper = mount(TestTargets, { props: { settings: makeState().settings } });
    await wrapper.get("input#target-entity").setValue("remote.x");
    await wrapper.get("input#target-label").setValue("Cinema");
    await wrapper.get("input#target-entity").trigger("input");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.text()).toContain("Only media_player entities");
    expect(save).not.toHaveBeenCalled();

    await wrapper.get("input#target-entity").setValue("media_player.otocuma_dp");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.text()).toContain("protected");
    expect(save).not.toHaveBeenCalled();
  });
});
