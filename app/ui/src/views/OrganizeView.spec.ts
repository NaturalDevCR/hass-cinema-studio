vi.mock("@/composables/useStudio", async (original) => {
  const actual = await original<typeof import("@/composables/useStudio")>();
  const refresh = vi.fn().mockResolvedValue(undefined);
  return { ...actual, useStudio: () => ({ ...actual.useStudio(), refresh }) };
});
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import OrganizeView from "./OrganizeView.vue";
import { ApiError, ui } from "@/api/client";
import { useConfirm } from "@/composables/useConfirm";
import { useStudio } from "@/composables/useStudio";
import { useToast } from "@/composables/useToast";
import { useI18n } from "@/i18n";
import { makeCollection, makeNormProfile, makeSeason } from "@/test/factories";
import { productionProfile } from "@/test/production-profile";

const mountView = () => mount(OrganizeView, { attachTo: document.body });
const wrappers: ReturnType<typeof mount>[] = [];
beforeEach(() => {
  vi.mocked(useStudio().refresh).mockReset().mockResolvedValue(undefined);
  useI18n().setLocale("en");
  useToast().toasts.value = [];
  const studio = useStudio();
  studio.loaded.value = true;
  studio.collections.value = [
    makeCollection({ id: "regular", name: "Regular" }),
    makeCollection({ id: "horror", name: "Horror", playback_mode: "sequential" }),
  ];
  studio.seasons.value = [
    makeSeason({ id: "regular", name: "Regular", builtin: true }),
    makeSeason({ id: "oct", name: "Halloween", start: "10-01", end: "10-31", collection_id: "horror" }),
  ];
  studio.normProfiles.value = [makeNormProfile({ id: "soft", name: "Soft" })];
  studio.procProfiles.value = [{ ...productionProfile, id: "compatibility-4k-loudness", name: "Compatibility" }];
  studio.assets.value = [];
});
afterEach(() => {
  wrappers.splice(0).forEach((w) => w.unmount());
  useConfirm().answer(false);
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});
function view() {
  const w = mountView();
  wrappers.push(w);
  return w;
}

it("exposes the five tabs and navigates them with the keyboard", async () => {
  const w = view();
  expect(w.findAll('[role="tab"]').map((tab) => tab.attributes("id"))).toEqual([
    "organize-tab-collections", "organize-tab-seasons", "organize-tab-loudness",
    "organize-tab-processing", "organize-tab-assets",
  ]);
  expect(w.get("#organize-tab-collections").attributes("aria-selected")).toBe("true");
  await w.get('[role="tablist"]').trigger("keydown", { key: "ArrowRight" });
  expect(w.get("#organize-tab-seasons").attributes("aria-selected")).toBe("true");
  await w.get('[role="tablist"]').trigger("keydown", { key: "End" });
  expect(w.get("#organize-tab-assets").attributes("tabindex")).toBe("0");
  await w.get('[role="tablist"]').trigger("keydown", { key: "ArrowRight" });
  expect(w.get("#organize-tab-collections").attributes("aria-selected")).toBe("true");
});

it("lists collections with their mode and processing profile, and opens the form to create or edit", async () => {
  const w = view();
  const rows = w.findAll("#organize-collections li");
  expect(rows).toHaveLength(2);
  expect(rows[1]!.text()).toContain("Horror");
  expect(rows[1]!.text()).toContain("Sequential");
  expect(rows[1]!.text()).toContain("Compatibility");
  await w.get('button[aria-label="Edit Horror"]').trigger("click");
  expect((document.body.querySelector('[data-test="name"]') as HTMLInputElement).value).toBe("Horror");
  expect(document.body.querySelector('[role="dialog"]')?.textContent).toContain("Edit collection");
});

it("never offers to delete the Regular collection", () => {
  const w = view();
  expect(w.find('button[aria-label="Delete Regular"]').exists()).toBe(false);
  expect(w.find('button[aria-label="Delete Horror"]').exists()).toBe(true);
});

it("confirms a collection deletion and refreshes", async () => {
  const remove = vi.spyOn(ui.collections, "remove").mockResolvedValue(undefined);
  const w = view();
  await w.get('button[aria-label="Delete Horror"]').trigger("click");
  expect(useConfirm().request.value?.danger).toBe(true);
  expect(remove).not.toHaveBeenCalled();
  useConfirm().answer(true);
  await flushPromises();
  expect(remove).toHaveBeenCalledExactlyOnceWith("horror");
  expect(useStudio().refresh).toHaveBeenCalled();
});

it("explains a 409 on collection deletion instead of showing the raw server text", async () => {
  vi.spyOn(ui.collections, "remove").mockRejectedValue(new ApiError(409, "Collection is referenced"));
  const w = view();
  await w.get('button[aria-label="Delete Horror"]').trigger("click");
  useConfirm().answer(true);
  await flushPromises();
  const message = "This collection still has clips or seasons. Move or delete them first.";
  expect(w.get('[data-test="organize-error"]').text()).toBe(message);
  expect(useToast().toasts.value.at(-1)).toMatchObject({ kind: "error", message });
});

it("shows the collection each season plays", async () => {
  const w = view();
  await w.get("#organize-tab-seasons").trigger("click");
  const rows = w.findAll("#organize-seasons li");
  expect(rows[1]!.text()).toContain("Halloween");
  expect(rows[1]!.text()).toContain("Horror");
});

it("shows season and collection when probing a date", async () => {
  vi.spyOn(ui.seasons, "resolve").mockResolvedValue({ date: "2026-10-31", season_id: "oct", collection_id: "horror" });
  const w = view();
  await w.get("#organize-tab-seasons").trigger("click");
  await w.get('input[type="date"]').setValue("2026-10-31");
  await flushPromises();
  const probe = w.get('[data-test="probe-result"]');
  expect(probe.text()).toContain("Halloween");
  expect(probe.text()).toContain("Horror");
});

it("lists loudness profiles and processing profiles in their own tabs", async () => {
  const w = view();
  await w.get("#organize-tab-loudness").trigger("click");
  expect(w.get("#organize-loudness").text()).toContain("Soft");
  await w.get("#organize-tab-processing").trigger("click");
  const panel = w.get("#organize-processing");
  expect(panel.text()).toContain("Compatibility");
  expect(panel.text()).toContain("3840 × 2160");
  await w.get('button[aria-label="Edit Compatibility"]').trigger("click");
  expect(document.body.querySelector('[data-test="json"]')).not.toBeNull();
});

it("shows the server detail when a processing profile is still in use", async () => {
  vi.spyOn(ui.procProfiles, "remove").mockRejectedValue(new ApiError(409, "Profile is used by collection regular"));
  const w = view();
  await w.get("#organize-tab-processing").trigger("click");
  await w.get('button[aria-label="Delete Compatibility"]').trigger("click");
  useConfirm().answer(true);
  await flushPromises();
  expect(w.get('[data-test="organize-error"]').text()).toBe("Profile is used by collection regular");
});

it("deletes a loudness profile after confirmation", async () => {
  const remove = vi.spyOn(ui.normProfiles, "remove").mockResolvedValue(undefined);
  const w = view();
  await w.get("#organize-tab-loudness").trigger("click");
  await w.get('button[aria-label="Delete Soft"]').trigger("click");
  useConfirm().answer(true);
  await flushPromises();
  expect(remove).toHaveBeenCalledExactlyOnceWith("soft");
});

it("renders the assets panel in the assets tab", async () => {
  useStudio().assets.value = [{ filename: "intro.mp4", size: 10, sha256: "a", status: "ready" }];
  const w = view();
  await w.get("#organize-tab-assets").trigger("click");
  expect(w.get("#organize-assets").text()).toContain("intro.mp4");
});
