import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CustomOrderList from "./CustomOrderList.vue";
import { useToast } from "@/composables/useToast";
import { makeClip } from "@/test/factories";

const { order } = vi.hoisted(() => ({ order: vi.fn() }));
vi.mock("@/api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/api/client")>()), ui: { collections: { order } } }));

const clips = () => ["a", "b", "c"].map((id) => makeClip({ id }));
const titles = (wrapper: ReturnType<typeof mount>) => wrapper.findAll("li").map((li) => li.find(".truncate").text());

describe("CustomOrderList", () => {
  beforeEach(() => { order.mockReset(); order.mockResolvedValue({}); useToast().toasts.value = []; });

  it("moves a clip up, emits order, and persists through the client", async () => {
    const wrapper = mount(CustomOrderList, { props: { collectionId: "c", clips: clips().slice(0, 2) } });
    await wrapper.get('[data-test="up-b"]').trigger("click");
    await flushPromises();
    expect(wrapper.emitted("update:order")?.[0]).toEqual([["b", "a"]]);
    expect(order).toHaveBeenCalledWith("c", ["b", "a"]);
    expect(titles(wrapper)).toEqual(["b", "a"]);
  });

  it("persists a drag and drop reorder", async () => {
    const wrapper = mount(CustomOrderList, { props: { collectionId: "c", clips: clips() } });
    const items = wrapper.findAll("li");
    const data: Record<string, string> = {};
    const dataTransfer = { setData: (k: string, v: string) => { data[k] = v; }, getData: (k: string) => data[k] };
    await items[0]!.trigger("dragstart", { dataTransfer });
    await items[2]!.trigger("drop", { dataTransfer });
    await flushPromises();
    expect(order).toHaveBeenCalledWith("c", ["b", "c", "a"]);
    expect(titles(wrapper)).toEqual(["b", "c", "a"]);
    expect(wrapper.emitted("update:order")?.[0]).toEqual([["b", "c", "a"]]);
  });

  it("keeps the old order, emits nothing and shows an error toast when the API rejects", async () => {
    order.mockRejectedValue(new Error("boom"));
    const wrapper = mount(CustomOrderList, { props: { collectionId: "c", clips: clips().slice(0, 2) } });
    await wrapper.get('[data-test="down-a"]').trigger("click");
    await flushPromises();
    expect(order).toHaveBeenCalledWith("c", ["b", "a"]);
    expect(titles(wrapper)).toEqual(["a", "b"]);
    expect(wrapper.emitted("update:order")).toBeUndefined();
    expect(useToast().toasts.value.map((t) => t.kind)).toEqual(["error"]);
    expect(useToast().toasts.value[0]!.message).toContain("boom");
  });

  it("does not show the new order while the request is still pending", async () => {
    let resolve!: () => void;
    order.mockReturnValue(new Promise<void>((r) => { resolve = r; }));
    const wrapper = mount(CustomOrderList, { props: { collectionId: "c", clips: clips().slice(0, 2) } });
    await wrapper.get('[data-test="up-b"]').trigger("click");
    expect(titles(wrapper)).toEqual(["a", "b"]);
    resolve();
    await flushPromises();
    expect(titles(wrapper)).toEqual(["b", "a"]);
  });
});
