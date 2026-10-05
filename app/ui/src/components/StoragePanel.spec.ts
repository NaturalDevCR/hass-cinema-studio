import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { makeState } from "@/test/system";
import StoragePanel from "./StoragePanel.vue";

describe("StoragePanel", () => {
  it("does not warn when free space is above the reserve", () => {
    const state = makeState();
    const wrapper = mount(StoragePanel, { props: { storage: state.storage, reserveBytes: state.settings.disk_reserve_bytes } });
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
  });

  it("warns when free space is below the reserve", () => {
    const state = makeState();
    const storage = { ...state.storage, free_bytes: 1_000_000_000 };
    const wrapper = mount(StoragePanel, { props: { storage, reserveBytes: state.settings.disk_reserve_bytes } });
    expect(wrapper.get('[data-test="low-space"]').text()).toContain("below the reserve");
  });

  it("shows the network filesystem warning", () => {
    const state = makeState();
    const wrapper = mount(StoragePanel, {
      props: { storage: { ...state.storage, network_fs: true }, reserveBytes: 0 },
    });
    expect(wrapper.text()).toContain("network filesystem");
  });
});
