import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { h, nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import Sheet from "@/components/Sheet.vue";
import { useI18n } from "@/i18n";

const mounted: VueWrapper[] = [];

function mountSheet(props: { open: boolean; title: string } = { open: true, title: "Edit clip" }) {
  const wrapper = mount(Sheet, {
    props,
    attachTo: document.body,
    global: { stubs: { teleport: true } },
    slots: {
      default: () => [h("button", { id: "first" }, "First"), h("button", { id: "last" }, "Last")],
    },
  });
  mounted.push(wrapper);
  return wrapper;
}

const press = (key: string, init: KeyboardEventInit = {}) =>
  document.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }));

beforeEach(() => useI18n().setLocale("en"));
afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount();
  document.body.innerHTML = "";
  document.body.style.overflow = "";
});

describe("Sheet", () => {
  it("renders nothing while closed", () => {
    const wrapper = mountSheet({ open: false, title: "Edit clip" });
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
  });

  it("renders an accessible modal dialog with title and content", () => {
    const wrapper = mountSheet();
    const dialog = wrapper.get('[role="dialog"]');
    expect(dialog.attributes("aria-modal")).toBe("true");
    const labelledBy = dialog.attributes("aria-labelledby")!;
    expect(wrapper.get(`#${labelledBy}`).text()).toBe("Edit clip");
    expect(dialog.text()).toContain("First");
  });

  it("emits close for Escape, the close button and the backdrop", async () => {
    const wrapper = mountSheet();
    press("Escape");
    expect(wrapper.emitted("close")).toHaveLength(1);
    await wrapper.get('button[aria-label="Close"]').trigger("click");
    expect(wrapper.emitted("close")).toHaveLength(2);
    await wrapper.get('[data-test="backdrop"]').trigger("click");
    expect(wrapper.emitted("close")).toHaveLength(3);
  });

  it("locks body scroll while open and restores it afterwards", async () => {
    document.body.style.overflow = "auto";
    const wrapper = mountSheet({ open: false, title: "t" });
    expect(document.body.style.overflow).toBe("auto");
    await wrapper.setProps({ open: true });
    expect(document.body.style.overflow).toBe("hidden");
    await wrapper.setProps({ open: false });
    expect(document.body.style.overflow).toBe("auto");
  });

  it("releases the scroll lock when unmounted while open", () => {
    document.body.style.overflow = "";
    const wrapper = mountSheet();
    expect(document.body.style.overflow).toBe("hidden");
    wrapper.unmount();
    mounted.length = 0;
    expect(document.body.style.overflow).toBe("");
  });

  it("moves focus into the dialog and gives it back on close", async () => {
    const trigger = document.createElement("button");
    document.body.append(trigger);
    trigger.focus();
    const wrapper = mountSheet({ open: false, title: "t" });
    await wrapper.setProps({ open: true });
    await flushPromises();
    expect(wrapper.get('[role="dialog"]').element.contains(document.activeElement)).toBe(true);
    await wrapper.setProps({ open: false });
    await flushPromises();
    expect(document.activeElement).toBe(trigger);
  });

  it("traps Tab and Shift+Tab inside the dialog", async () => {
    const wrapper = mountSheet();
    await flushPromises();
    const close = wrapper.get('button[aria-label="Close"]').element as HTMLElement;
    const last = wrapper.get("#last").element as HTMLElement;

    last.focus();
    const forward = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    document.dispatchEvent(forward);
    expect(forward.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(close);

    const backward = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true });
    document.dispatchEvent(backward);
    expect(backward.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(last);
  });

  it("only the top-most modal reacts to Escape", async () => {
    const lower = mountSheet({ open: true, title: "lower" });
    const upper = mountSheet({ open: true, title: "upper" });
    await nextTick();
    press("Escape");
    expect(upper.emitted("close")).toHaveLength(1);
    expect(lower.emitted("close")).toBeUndefined();
  });
});
