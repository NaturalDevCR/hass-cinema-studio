import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CustomOrderList from "./CustomOrderList.vue";
import { makeClip } from "@/test/factories";

const { order } = vi.hoisted(() => ({ order: vi.fn() }));
vi.mock("@/api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/api/client")>()), ui: { collections: { order } } }));

describe("CustomOrderList", () => {
  beforeEach(() => order.mockReset());
  it("moves a clip up, emits order, and persists through the client", async () => {
    const wrapper = mount(CustomOrderList, { props: { collectionId: "c", clips: [makeClip({ id: "a" }), makeClip({ id: "b" })] } });
    await wrapper.get('[data-test="up-b"]').trigger("click");
    expect(wrapper.emitted("update:order")?.[0]).toEqual([["b", "a"]]);
    expect(order).toHaveBeenCalledWith("c", ["b", "a"]);
  });
});
