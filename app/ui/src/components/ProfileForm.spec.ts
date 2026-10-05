vi.mock("@/composables/useJobs", () => {
  const refresh = vi.fn().mockResolvedValue(undefined);
  return { useJobs: () => ({ refresh }) };
});
vi.mock("@/composables/useStudio", async (original) => {
  const actual = await original<typeof import("@/composables/useStudio")>();
  const refresh = vi.fn().mockResolvedValue(undefined),
    refreshClips = vi.fn().mockResolvedValue(undefined);
  return {
    ...actual,
    useStudio: () => ({ ...actual.useStudio(), refresh, refreshClips }),
  };
});
import { mount, flushPromises } from "@vue/test-utils";
import { beforeEach, it, expect, vi } from "vitest";
import ProfileForm from "./ProfileForm.vue";
import { useConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { ui } from "@/api/client";
import { makeNormProfile } from "@/test/factories";
beforeEach(() => {
  useToast().toasts.value = [];
});
it("saves via PATCH and toasts how many clips the server re-renders, without a confirm step", async () => {
  const profile = makeNormProfile({ id: "soft" });
  const update = vi.spyOn(ui.normProfiles, "update").mockResolvedValue({ profile, affected_clip_ids: ["a", "b"] });
  const apply = vi.spyOn(ui.normProfiles, "apply").mockResolvedValue({ queued: 2 });
  const w = mount(ProfileForm, { props: { profile } });
  await w.get("form").trigger("submit");
  await flushPromises();
  expect(update).toHaveBeenCalledWith("soft", expect.objectContaining({ target_lufs: -16 }));
  expect(useConfirm().request.value).toBeNull();
  expect(apply).not.toHaveBeenCalled();
  expect(useToast().toasts.value.map((t) => t.message)).toContain("2 clips will be re-rendered");
  expect(w.emitted("saved")).toHaveLength(1);
  update.mockRestore();
  apply.mockRestore();
});
it("does not announce a re-render when no clip is affected", async () => {
  const profile = makeNormProfile({ id: "soft" });
  const update = vi.spyOn(ui.normProfiles, "update").mockResolvedValue({ profile, affected_clip_ids: [] });
  const w = mount(ProfileForm, { props: { profile } });
  await w.get("form").trigger("submit");
  await flushPromises();
  expect(useToast().toasts.value.some((t) => /re-rendered/.test(t.message))).toBe(false);
  expect(w.emitted("saved")).toHaveLength(1);
  update.mockRestore();
});
it("rejects blank names and out-of-range loudness", async () => {
  const create = vi.spyOn(ui.normProfiles, "create");
  const w = mount(ProfileForm);
  await w.get("form").trigger("submit");
  expect(create).not.toHaveBeenCalled();
  await w.get('[data-test="name"]').setValue("Test");
  await w.get('[data-test="target_lufs"]').setValue("-31");
  await w.get("form").trigger("submit");
  expect(create).not.toHaveBeenCalled();
  create.mockRestore();
});
it("shows a save failure inline and allows retrying", async () => {
  const profile = makeNormProfile({ id: "soft" });
  const update = vi
    .spyOn(ui.normProfiles, "update")
    .mockRejectedValueOnce(new Error("disk full"))
    .mockResolvedValue({ profile, affected_clip_ids: [] });
  const w = mount(ProfileForm, { props: { profile } });
  await w.get("form").trigger("submit");
  await flushPromises();
  expect(w.get('[role="alert"]').text()).toBe("disk full");
  expect(w.emitted("saved")).toBeUndefined();
  await w.get("form").trigger("submit");
  await flushPromises();
  expect(update).toHaveBeenCalledTimes(2);
  expect(w.emitted("saved")).toHaveLength(1);
  update.mockRestore();
});

it("names every profile slider and announces the formatted values from the number inputs", async () => {
  const w = mount(ProfileForm);
  const sliders = w.findAll('input[type="range"]');
  expect(sliders.map((s) => s.attributes("aria-label"))).toEqual([
    "Target loudness (LUFS)", "Peak ceiling (dBTP)", "Loudness range (LU)",
  ]);
  expect(sliders.map((s) => s.attributes("aria-valuetext"))).toEqual(["−16.0 LUFS", "−1.5 dBTP", "11.0 LU"]);
  await w.get('[data-test="true_peak"]').setValue("-2");
  expect(sliders[1]!.attributes("aria-valuetext")).toBe("−2.0 dBTP");
  w.unmount();
});
