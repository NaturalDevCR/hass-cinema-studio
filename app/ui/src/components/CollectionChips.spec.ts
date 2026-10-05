import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import CollectionChips from "./CollectionChips.vue";
import { makeCollection } from "@/test/factories";

describe("CollectionChips", () => {
  it("shows counts and emits the selected collection", async () => {
    const wrapper = mount(CollectionChips, { props: {
      collections: [makeCollection({ id: "regular", name: "Regular", playback_mode: "random" })],
      modelValue: null, counts: { regular: 3 }, total: 3,
    } });
    expect(wrapper.text()).toContain("3");
    expect(wrapper.text()).toContain("random");
    await wrapper.get('[data-test="collection-regular"]').trigger("click");
    expect(wrapper.emitted("update:modelValue")?.[0]).toEqual(["regular"]);
  });
});
