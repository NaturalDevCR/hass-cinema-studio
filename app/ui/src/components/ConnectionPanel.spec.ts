import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeState } from "@/test/system";
import ConnectionPanel from "./ConnectionPanel.vue";

const rotateToken = vi.fn();
const refresh = vi.fn();
const confirm = vi.fn();
vi.mock("@/api/client", () => ({
  ui: { rotateToken: (...a: unknown[]) => rotateToken(...a), token: vi.fn() },
  messageOf: (e: unknown) => String(e),
}));
vi.mock("@/composables/useStudio", () => ({ useStudio: () => ({ refresh }) }));
vi.mock("@/composables/useConfirm", () => ({ useConfirm: () => ({ confirm }) }));
vi.mock("@/composables/useToast", () => ({ useToast: () => ({ push: vi.fn() }) }));

describe("ConnectionPanel", () => {
  beforeEach(() => {
    rotateToken.mockReset();
    refresh.mockReset();
    confirm.mockReset();
  });

  it("rotates the token after confirmation and force-refreshes the state", async () => {
    confirm.mockResolvedValue(true);
    rotateToken.mockResolvedValue({ api_token_masked: "••••new" });
    const wrapper = mount(ConnectionPanel, { props: { state: makeState() } });
    await wrapper.get('[data-test="rotate-token"]').trigger("click");
    await flushPromises();
    expect(rotateToken).toHaveBeenCalledOnce();
    expect(refresh).toHaveBeenCalledWith({ force: true });
  });

  it("does not rotate when the confirmation is declined", async () => {
    confirm.mockResolvedValue(false);
    const wrapper = mount(ConnectionPanel, { props: { state: makeState() } });
    await wrapper.get('[data-test="rotate-token"]').trigger("click");
    await flushPromises();
    expect(rotateToken).not.toHaveBeenCalled();
  });
});
