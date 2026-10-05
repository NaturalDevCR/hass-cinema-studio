import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeState } from "@/test/system";
import DefaultsPanel from "./DefaultsPanel.vue";

const save = vi.fn();
vi.mock("@/composables/useSettingsSave", async () => {
  const { ref } = await import("vue");
  return { useSettingsSave: () => ({ pending: ref(false), error: ref<string | null>(null), save }) };
});

const GIB = 1024 ** 3;
const value = (wrapper: ReturnType<typeof mount>, id: string) =>
  (wrapper.get(`input#${id}`).element as HTMLInputElement).value;

describe("DefaultsPanel", () => {
  beforeEach(() => {
    save.mockReset();
    save.mockResolvedValue(true);
  });

  it("shows current values with the reserve converted from bytes to GB", () => {
    const settings = { ...makeState().settings, disk_reserve_bytes: 2 * GIB };
    const wrapper = mount(DefaultsPanel, { props: { settings } });
    expect(value(wrapper, "defaults-lead")).toBe("2");
    expect(value(wrapper, "defaults-tail")).toBe("2");
    expect(value(wrapper, "defaults-upload")).toBe("4096");
    expect(value(wrapper, "defaults-duration")).toBe("7200");
    expect(value(wrapper, "defaults-reserve")).toBe("2");
  });

  it("saves edited values and converts GB back to bytes", async () => {
    const wrapper = mount(DefaultsPanel, { props: { settings: makeState().settings } });
    await wrapper.get("input#defaults-lead").setValue("3.5");
    await wrapper.get("input#defaults-tail").setValue("0");
    await wrapper.get("input#defaults-upload").setValue("2048");
    await wrapper.get("input#defaults-duration").setValue("3600");
    await wrapper.get("input#defaults-reserve").setValue("1.5");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(save).toHaveBeenCalledWith({
      default_lead_in: 3.5,
      default_tail_out: 0,
      max_upload_mb: 2048,
      max_duration_s: 3600,
      disk_reserve_bytes: 1.5 * GIB,
    });
  });

  it("rejects margins outside 0-10 seconds and invalid limits without saving", async () => {
    const wrapper = mount(DefaultsPanel, { props: { settings: makeState().settings } });
    await wrapper.get("input#defaults-lead").setValue("11");
    await wrapper.get("form").trigger("submit");
    expect(save).not.toHaveBeenCalled();
    expect(wrapper.get('[role="alert"]').text()).toContain("0 and 10");

    await wrapper.get("input#defaults-lead").setValue("2");
    await wrapper.get("input#defaults-upload").setValue("0");
    await wrapper.get("form").trigger("submit");
    expect(save).not.toHaveBeenCalled();
    expect(wrapper.get('[role="alert"]').text()).toContain("positive");
  });

  it("resyncs fields when saved settings change", async () => {
    const wrapper = mount(DefaultsPanel, { props: { settings: makeState().settings } });
    await wrapper.setProps({ settings: { ...makeState().settings, default_lead_in: 4, disk_reserve_bytes: 3 * GIB } });
    expect(value(wrapper, "defaults-lead")).toBe("4");
    expect(value(wrapper, "defaults-reserve")).toBe("3");
  });
});
