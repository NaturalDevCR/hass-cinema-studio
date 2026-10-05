import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import { useConfirm } from "@/composables/useConfirm";
import { useI18n } from "@/i18n";

const mountDialog = () =>
  mount(ConfirmDialog, { attachTo: document.body, global: { stubs: { teleport: true } } });

beforeEach(() => useI18n().setLocale("en"));
afterEach(() => {
  document.body.innerHTML = "";
  document.body.style.overflow = "";
});

describe("ConfirmDialog / useConfirm", () => {
  it("is hidden until confirm() is called", () => {
    const wrapper = mountDialog();
    expect(wrapper.find('[role="alertdialog"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("resolves true when confirmed and shows the supplied copy", async () => {
    const wrapper = mountDialog();
    const answer = useConfirm().confirm({
      title: "Delete clip?",
      message: "This removes the original too.",
      confirmLabel: "Delete forever",
      danger: true,
    });
    await flushPromises();
    const dialog = wrapper.get('[role="alertdialog"]');
    expect(dialog.text()).toContain("Delete clip?");
    expect(dialog.text()).toContain("This removes the original too.");
    expect(wrapper.get('[data-test="confirm"]').text()).toBe("Delete forever");
    expect(wrapper.get('[data-test="confirm"]').classes()).toContain("btn-danger");
    await wrapper.get('[data-test="confirm"]').trigger("click");
    await expect(answer).resolves.toBe(true);
    await flushPromises();
    expect(wrapper.find('[role="alertdialog"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("resolves false on cancel, Escape and backdrop click", async () => {
    const wrapper = mountDialog();
    const { confirm } = useConfirm();

    let answer = confirm({ title: "A" });
    await flushPromises();
    await wrapper.get('[data-test="cancel"]').trigger("click");
    await expect(answer).resolves.toBe(false);

    answer = confirm({ title: "B" });
    await flushPromises();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await expect(answer).resolves.toBe(false);

    answer = confirm({ title: "C" });
    await flushPromises();
    await wrapper.get('[data-test="backdrop"]').trigger("click");
    await expect(answer).resolves.toBe(false);
    wrapper.unmount();
  });

  it("falls back to localized default copy", async () => {
    const wrapper = mountDialog();
    const answer = useConfirm().confirm();
    await flushPromises();
    expect(wrapper.get('[role="alertdialog"]').text()).toContain("Are you sure?");
    expect(wrapper.get('[data-test="confirm"]').text()).toBe("Confirm");
    expect(wrapper.get('[data-test="cancel"]').text()).toBe("Cancel");
    await wrapper.get('[data-test="cancel"]').trigger("click");
    await answer;
    wrapper.unmount();
  });

  it("cancels the previous question when a new one arrives", async () => {
    const wrapper = mountDialog();
    const { confirm } = useConfirm();
    const first = confirm({ title: "First" });
    const second = confirm({ title: "Second" });
    await expect(first).resolves.toBe(false);
    await flushPromises();
    expect(wrapper.text()).toContain("Second");
    await wrapper.get('[data-test="confirm"]').trigger("click");
    await expect(second).resolves.toBe(true);
    wrapper.unmount();
  });
});
