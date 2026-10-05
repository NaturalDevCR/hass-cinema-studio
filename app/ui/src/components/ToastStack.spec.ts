import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ToastStack from "@/components/ToastStack.vue";
import { useToast } from "@/composables/useToast";
import { useI18n } from "@/i18n";

const mountStack = () => mount(ToastStack, { attachTo: document.body, global: { stubs: { teleport: true } } });

beforeEach(() => {
  vi.useFakeTimers();
  useI18n().setLocale("en");
});
afterEach(() => {
  const { toasts } = useToast();
  toasts.value = [];
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("ToastStack", () => {
  it("is one persistent polite live region, present before any toast", () => {
    const wrapper = mountStack();
    const region = wrapper.get('[data-test="toasts"]');
    expect(region.attributes("role")).toBe("status");
    expect(region.attributes("aria-live")).toBe("polite");
    expect(region.text()).toBe("");
    wrapper.unmount();
  });

  it("keeps phone toasts below the safe-area header and desktop toasts at bottom-right", () => {
    const wrapper = mountStack();
    const classes = wrapper.get('[data-test="toasts"]').classes();
    expect(classes).toContain("top-[calc(3.5rem+env(safe-area-inset-top,0px)+0.75rem)]");
    expect(classes).toContain("md:top-auto");
    expect(classes).toContain("md:bottom-4");
    expect(classes).toContain("md:right-4");
    expect(classes.filter((c) => c.startsWith("bottom-"))).toEqual([]);
    wrapper.unmount();
  });

  it("renders toasts inside that region without per-item roles", async () => {
    const wrapper = mountStack();
    const { push } = useToast();
    push("Saved", "success");
    push("Broke", "error");
    await flushPromises();
    const region = wrapper.get('[data-test="toasts"]');
    expect(region.text()).toContain("Saved");
    expect(region.text()).toContain("Broke");
    expect(region.findAll("[role]")).toHaveLength(0);
    expect(region.findAll("[data-kind]").map((el) => el.attributes("data-kind"))).toEqual(["success", "error"]);
    wrapper.unmount();
  });

  it("keeps the dismiss buttons reachable (no inert ancestor) and they dismiss", async () => {
    const wrapper = mountStack();
    useToast().push("Hello");
    await flushPromises();
    const button = wrapper.get('button[aria-label="Dismiss notification"]');
    expect(button.element.closest("[inert]")).toBeNull();
    await button.trigger("click");
    expect(wrapper.find('button[aria-label="Dismiss notification"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
