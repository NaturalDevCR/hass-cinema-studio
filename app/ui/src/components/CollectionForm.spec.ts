vi.mock("@/composables/useStudio", async (original) => {
  const actual = await original<typeof import("@/composables/useStudio")>();
  const refresh = vi.fn().mockResolvedValue(undefined);
  return { ...actual, useStudio: () => ({ ...actual.useStudio(), refresh }) };
});
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CollectionForm from "./CollectionForm.vue";
import { ui } from "@/api/client";
import { useStudio } from "@/composables/useStudio";
import { useToast } from "@/composables/useToast";
import { useI18n } from "@/i18n";
import { makeCollection } from "@/test/factories";
import { productionProfile } from "@/test/production-profile";

const selected = (w: ReturnType<typeof mount>, key: string) =>
  (w.get(`[data-test="${key}"]`).element as HTMLSelectElement).value;

beforeEach(() => {
  useI18n().setLocale("en");
  useToast().toasts.value = [];
  useStudio().procProfiles.value = [
    { ...productionProfile, id: "compatibility-4k-loudness", name: "Compatibility 4K" },
    { ...productionProfile, id: "intro", name: "With intro" },
  ];
});

describe("CollectionForm", () => {
  it("creates a collection with the chosen playback mode and processing profile", async () => {
    const created = makeCollection({ id: "horror", name: "Horror", playback_mode: "sequential" });
    const create = vi.spyOn(ui.collections, "create").mockResolvedValue(created);
    const w = mount(CollectionForm);
    await w.get('[data-test="name"]').setValue("  Horror ");
    await w.get('[data-test="mode-sequential"]').setValue(true);
    await w.get('[data-test="profile"]').setValue("intro");
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(create).toHaveBeenCalledExactlyOnceWith({
      name: "Horror",
      color: expect.stringMatching(/^#[0-9a-f]{6}$/i),
      icon: "mdi:filmstrip-box",
      playback_mode: "sequential",
      processing_profile_id: "intro",
    });
    expect(w.emitted("saved")).toEqual([[created]]);
    create.mockRestore();
  });

  it("defaults to random playback and the first processing profile", () => {
    const w = mount(CollectionForm);
    expect((w.get('[data-test="mode-random"]').element as HTMLInputElement).checked).toBe(true);
    expect(selected(w, "profile")).toBe("compatibility-4k-loudness");
    expect(w.find('[data-test="enabled"]').exists()).toBe(false);
  });

  it.each([
    ["random", "Each play picks a clip at random"],
    ["sequential", "Clips play one after another in the order they were added"],
    ["custom", "Clips play in the order you set by dragging them in the Library"],
  ])("explains the %s playback mode", (mode, text) => {
    const w = mount(CollectionForm);
    expect(w.get(`[data-test="mode-${mode}-hint"]`).text()).toContain(text);
  });

  it("explains the modes in Spanish", () => {
    useI18n().setLocale("es");
    const w = mount(CollectionForm);
    expect(w.get('[data-test="mode-random-hint"]').text()).toContain("al azar");
    useI18n().setLocale("en");
  });

  it("patches an existing collection, including enabled, and reports the clips it re-renders", async () => {
    const collection = makeCollection({ id: "horror", name: "Horror", playback_mode: "custom", enabled: true });
    const update = vi.spyOn(ui.collections, "update").mockResolvedValue({
      collection: { ...collection, enabled: false }, affected_clip_ids: ["a", "b"],
    });
    const w = mount(CollectionForm, { props: { collection } });
    expect((w.get('[data-test="mode-custom"]').element as HTMLInputElement).checked).toBe(true);
    await w.get('[data-test="enabled"]').setValue(false);
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(update).toHaveBeenCalledExactlyOnceWith("horror", {
      name: "Horror",
      color: collection.color,
      icon: collection.icon,
      playback_mode: "custom",
      processing_profile_id: "compatibility-4k-loudness",
      enabled: false,
    });
    expect(useToast().toasts.value.map((t) => t.message)).toContain("2 clips will be re-rendered");
    expect(w.emitted("saved")).toHaveLength(1);
    update.mockRestore();
  });

  it("keeps a processing profile that no longer exists selectable instead of silently swapping it", () => {
    const w = mount(CollectionForm, {
      props: { collection: makeCollection({ id: "old", processing_profile_id: "deleted-profile" }) },
    });
    expect(selected(w, "profile")).toBe("deleted-profile");
  });

  it("requires a name and shows server failures inline", async () => {
    const create = vi.spyOn(ui.collections, "create").mockRejectedValueOnce(new Error("Collection exists"));
    const w = mount(CollectionForm);
    await w.get("form").trigger("submit");
    expect(create).not.toHaveBeenCalled();
    expect(w.get('[role="alert"]').text()).toBe("Enter a name.");
    await w.get('[data-test="name"]').setValue("Dup");
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(w.get('[role="alert"]').text()).toBe("Collection exists");
    expect(w.emitted("saved")).toBeUndefined();
    create.mockRestore();
  });

  it("switches to update mode after a create so a retry cannot create a duplicate", async () => {
    const created = makeCollection({ id: "once", name: "Once" });
    const create = vi.spyOn(ui.collections, "create").mockResolvedValue(created);
    const update = vi.spyOn(ui.collections, "update").mockResolvedValue({ collection: created, affected_clip_ids: [] });
    vi.mocked(useStudio().refresh).mockRejectedValueOnce(new Error("offline"));
    const w = mount(CollectionForm);
    await w.get('[data-test="name"]').setValue("Once");
    await w.get("form").trigger("submit");
    await flushPromises();
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(create).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledWith("once", expect.objectContaining({ name: "Once" }));
    create.mockRestore();
    update.mockRestore();
  });
});
