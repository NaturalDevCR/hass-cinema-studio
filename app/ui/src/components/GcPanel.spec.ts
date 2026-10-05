import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeState } from "@/test/system";
import GcPanel from "./GcPanel.vue";

const gcRun = vi.fn();
const refresh = vi.fn();
vi.mock("@/api/client", () => ({ ui: { gcRun: (...args: unknown[]) => gcRun(...args) }, messageOf: (e: unknown) => String(e) }));
vi.mock("@/composables/useStudio", () => ({ useStudio: () => ({ refresh }) }));
vi.mock("@/composables/useToast", () => ({ useToast: () => ({ push: vi.fn() }) }));

describe("GcPanel", () => {
  beforeEach(() => { gcRun.mockReset(); refresh.mockReset(); });

  it("shows the halt reason and runs garbage collection", async () => {
    gcRun.mockResolvedValue({ deleted: 3, halted_reason: null });
    const state = makeState();
    state.gc = { enabled: false, halted_reason: "consumer file is invalid", last_run_at: null, deleted_last_run: 0 };
    const wrapper = mount(GcPanel, { props: { state, consumers: state.consumers } });
    expect(wrapper.text()).toContain("consumer file is invalid");
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(gcRun).toHaveBeenCalledOnce();
    expect(refresh).toHaveBeenCalledOnce();
  });
});
