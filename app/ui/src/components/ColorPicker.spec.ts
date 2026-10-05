import { mount } from "@vue/test-utils";
import { it, expect } from "vitest";
import ColorPicker from "./ColorPicker.vue";
it("offers 12 swatches and only accepts six-digit hex colors", async () => {
  const w = mount(ColorPicker, { props: { modelValue: "#8b5cf6" } });
  expect(w.findAll('[data-test="swatch"]')).toHaveLength(12);
  await w.get("input").setValue("#ABCDEF");
  expect(w.emitted("update:modelValue")?.at(-1)).toEqual(["#abcdef"]);
  await w.get("input").setValue("#xyz");
  expect(w.find('[role="alert"]').exists()).toBe(true);
  expect(w.emitted("valid")?.at(-1)).toEqual([false]);
  await w.get("input").setValue("#123456");
  expect(w.find('[role="alert"]').exists()).toBe(false);
});

it.each([["#8b5cf6", true], ["invalid", false]])("emits initial validity for %s", (modelValue, valid) => {
  const w = mount(ColorPicker, { props: { modelValue: modelValue as string } });
  expect(w.emitted("valid")).toEqual([[valid]]);
});
