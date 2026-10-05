import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeState } from "@/test/system";
import GcPanel from "./GcPanel.vue";

const gcRun = vi.fn();
const refresh = vi.fn();
const push = vi.fn();
vi.mock("@/api/client", () => ({
  ui: { gcRun: (...args: unknown[]) => gcRun(...args) },
  messageOf: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));
vi.mock("@/composables/useStudio", () => ({ useStudio: () => ({ refresh }) }));
vi.mock("@/composables/useToast", () => ({ useToast: () => ({ push }) }));

const runButton = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll("button").find((button) => button.text() === "Run now")!;

describe("GcPanel", () => {
  beforeEach(() => {
    gcRun.mockReset();
    refresh.mockReset();
    push.mockReset();
  });

  it("shows the halt reason and runs garbage collection with a success toast", async () => {
    gcRun.mockResolvedValue({ deleted: 3, halted_reason: null });
    const state = makeState();
    state.gc = { enabled: false, halted_reason: "consumer file is invalid", last_run_at: null, deleted_last_run: 0 };
    const wrapper = mount(GcPanel, { props: { state } });
    expect(wrapper.text()).toContain("Garbage collection is halted");
    expect(wrapper.get('[role="alert"]').text()).toBe("consumer file is invalid");
    await runButton(wrapper).trigger("click");
    await flushPromises();
    expect(gcRun).toHaveBeenCalledOnce();
    expect(refresh).toHaveBeenCalledWith({ force: true });
    expect(push).toHaveBeenCalledWith("Deleted 3 files", "success");
  });

  it("shows the enabled state", () => {
    const wrapper = mount(GcPanel, { props: { state: makeState() } });
    expect(wrapper.text()).toContain("Garbage collection is enabled");
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
  });

  it("toasts the halt reason as an error when a run halts", async () => {
    gcRun.mockResolvedValue({ deleted: 0, halted_reason: "network filesystem" });
    const wrapper = mount(GcPanel, { props: { state: makeState() } });
    await runButton(wrapper).trigger("click");
    await flushPromises();
    expect(push).toHaveBeenCalledWith("network filesystem", "error");
  });

  it("shows an inline error when the run fails and re-enables the button", async () => {
    gcRun.mockRejectedValue(new Error("boom"));
    const wrapper = mount(GcPanel, { props: { state: makeState() } });
    await runButton(wrapper).trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe("boom");
    expect(refresh).not.toHaveBeenCalled();
    expect(runButton(wrapper).attributes("disabled")).toBeUndefined();
  });

  it("renders the consumers table", () => {
    const state = makeState();
    state.consumers = [{ consumer_id: "player-1", last_seen_at: null, held_revision: 4, file_present: true, pins: 2 }];
    const wrapper = mount(GcPanel, { props: { state } });
    const cells = wrapper.findAll("tbody td").map((cell) => cell.text());
    expect(cells).toEqual(["player-1", "Yes", "4", "2"]);
  });
});
