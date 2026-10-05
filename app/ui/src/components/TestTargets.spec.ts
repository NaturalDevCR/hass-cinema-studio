import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Settings } from "@/api/types";
import { makeState } from "@/test/system";
import TestTargets from "./TestTargets.vue";

const save = vi.fn();
vi.mock("@/composables/useSettingsSave", async () => {
  const { ref } = await import("vue");
  return { useSettingsSave: () => ({ pending: ref(false), error: ref<string | null>(null), save }) };
});

function settings(overrides: Partial<Settings> = {}): Settings {
  return { ...makeState().settings, ...overrides };
}
async function fill(wrapper: ReturnType<typeof mount>, label: string, entity: string) {
  await wrapper.get("input#target-label").setValue(label);
  await wrapper.get("input#target-entity").setValue(entity);
  await wrapper.get("form").trigger("submit");
  await flushPromises();
}

describe("TestTargets", () => {
  beforeEach(() => {
    save.mockReset();
    save.mockResolvedValue(true);
    vi.unstubAllGlobals();
  });

  it("rejects non-media-player and protected entities with explanations", async () => {
    const wrapper = mount(TestTargets, { props: { settings: settings() } });
    await fill(wrapper, "Cinema", "remote.x");
    expect(wrapper.text()).toContain("Only media_player entities");
    expect(save).not.toHaveBeenCalled();

    await fill(wrapper, "Cinema", "media_player.otocuma_dp");
    expect(wrapper.text()).toContain("media_player.otocuma_dp is protected");
    expect(save).not.toHaveBeenCalled();
  });

  it("rejects a duplicate entity_id", async () => {
    const existing = [{ id: "t1", label: "Lounge", entity_id: "media_player.lounge" }];
    const wrapper = mount(TestTargets, { props: { settings: settings({ test_targets: existing }) } });
    await fill(wrapper, "Again", "media_player.lounge");
    expect(wrapper.text()).toContain("already a test device");
    expect(save).not.toHaveBeenCalled();
  });

  it("adds a trimmed target with a generated id and clears the form", async () => {
    vi.stubGlobal("crypto", { randomUUID: undefined });
    const existing = [{ id: "t1", label: "Lounge", entity_id: "media_player.lounge" }];
    const wrapper = mount(TestTargets, { props: { settings: settings({ test_targets: existing }) } });
    await fill(wrapper, "  Cinema  ", " media_player.cinema ");
    expect(save).toHaveBeenCalledOnce();
    const patch = save.mock.calls[0]![0] as Pick<Settings, "test_targets">;
    expect(patch.test_targets).toHaveLength(2);
    expect(patch.test_targets[0]).toEqual(existing[0]);
    expect(patch.test_targets[1]).toMatchObject({ label: "Cinema", entity_id: "media_player.cinema" });
    expect(patch.test_targets[1]!.id).toMatch(/^target-/);
    expect((wrapper.get("input#target-label").element as HTMLInputElement).value).toBe("");
    expect((wrapper.get("input#target-entity").element as HTMLInputElement).value).toBe("");
  });

  it("removes a target by id", async () => {
    const existing = [
      { id: "t1", label: "Lounge", entity_id: "media_player.lounge" },
      { id: "t2", label: "Cinema", entity_id: "media_player.cinema" },
    ];
    const wrapper = mount(TestTargets, { props: { settings: settings({ test_targets: existing }) } });
    await wrapper.get('button[aria-label="Remove Lounge"]').trigger("click");
    expect(save).toHaveBeenCalledWith({ test_targets: [existing[1]] });
  });

  it("saves the protected list de-duplicated and validated", async () => {
    const wrapper = mount(TestTargets, { props: { settings: settings() } });
    const area = wrapper.get("textarea#protected-entities");
    await area.setValue("media_player.a\nlight.b  media_player.a\n");
    await wrapper.get("button.btn.mt-2").trigger("click");
    expect(save).toHaveBeenCalledWith({ protected_entities: ["media_player.a", "light.b"] });

    save.mockClear();
    await area.setValue("sensor.nope");
    await wrapper.get("button.btn.mt-2").trigger("click");
    expect(save).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("Use valid media_player");
  });

  it("resyncs the protected textarea when the saved settings change", async () => {
    const wrapper = mount(TestTargets, { props: { settings: settings() } });
    const area = wrapper.get("textarea#protected-entities");
    expect((area.element as HTMLTextAreaElement).value).toBe("media_player.otocuma_dp\ncover.ocl_screen_projector");
    await wrapper.setProps({ settings: settings({ protected_entities: ["light.new"] }) });
    expect((area.element as HTMLTextAreaElement).value).toBe("light.new");
  });
});
