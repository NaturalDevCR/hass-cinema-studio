import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { useI18n } from "@/i18n";
import CollectionChips from "./CollectionChips.vue";
import { makeCollection } from "@/test/factories";

describe("CollectionChips", () => {
  it("shows counts and emits the selected collection", async () => {
    const wrapper = mount(CollectionChips, { props: {
      collections: [makeCollection({ id: "regular", name: "Regular", playback_mode: "random" })],
      modelValue: null, counts: { regular: 3 }, total: 3,
    } });
    expect(wrapper.text()).toContain("3");
    expect(wrapper.text()).toContain("Random");
    expect(wrapper.text()).not.toContain("random");
    await wrapper.get('[data-test="collection-regular"]').trigger("click");
    expect(wrapper.emitted("update:modelValue")?.[0]).toEqual(["regular"]);
  });

  it("localizes the playback mode badge", () => {
    const modes = ["random", "sequential", "custom"] as const;
    const mountModes = () => mount(CollectionChips, { props: {
      collections: modes.map((mode) => makeCollection({ id: mode, name: `c-${mode}`, playback_mode: mode })),
      modelValue: null, counts: {}, total: 0,
    } });
    const { setLocale } = useI18n();
    setLocale("en");
    const en = mountModes().text();
    expect(["Random", "Sequential", "Custom"].every((label) => en.includes(label))).toBe(true);
    setLocale("es");
    const es = mountModes().text();
    expect(["Aleatorio", "Secuencial", "Personalizado"].every((label) => es.includes(label))).toBe(true);
    setLocale("en");
  });
});
