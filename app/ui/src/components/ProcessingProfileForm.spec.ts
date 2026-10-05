vi.mock("@/composables/useStudio", async (original) => {
  const actual = await original<typeof import("@/composables/useStudio")>();
  const refresh = vi.fn().mockResolvedValue(undefined);
  return { ...actual, useStudio: () => ({ ...actual.useStudio(), refresh }) };
});
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProcessingProfileForm from "./ProcessingProfileForm.vue";
import { ui } from "@/api/client";
import type { ProcessingProfile, ProcessingProfileSettings } from "@/api/types";
import { useStudio } from "@/composables/useStudio";
import { useToast } from "@/composables/useToast";
import { useI18n } from "@/i18n";
import { productionProfile } from "@/test/production-profile";

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const jsonOf = (w: ReturnType<typeof mount>) =>
  JSON.parse((w.get('[data-test="json"]').element as HTMLTextAreaElement).value) as ProcessingProfileSettings;
const value = (w: ReturnType<typeof mount>, key: string) =>
  (w.get(`[data-test="${key}"]`).element as HTMLInputElement | HTMLSelectElement).value;
const saved = (settings: ProcessingProfileSettings, id = "created"): ProcessingProfile => ({ id, name: "x", settings });

beforeEach(() => {
  useI18n().setLocale("en");
  useToast().toasts.value = [];
  useStudio().assets.value = [
    { filename: "treebu-hotels-intro.mp4", size: 1000, sha256: "a", status: "ready" },
    { filename: "other.mp4", size: 1000, sha256: "b", status: "ready" },
  ];
});

describe("ProcessingProfileForm", () => {
  it("shows the production profile in the structured sections and the Advanced JSON", () => {
    const w = mount(ProcessingProfileForm, { props: { profile: productionProfile } });
    expect(jsonOf(w)).toEqual(productionProfile.settings);
    expect(value(w, "name")).toBe("4K con intro y audio normalizado");
    expect(value(w, "resolution")).toBe("4k");
    expect(value(w, "fps")).toBe("24");
    expect(value(w, "crf")).toBe("23");
    expect(value(w, "maxrate")).toBe("20000");
    expect(value(w, "audio-bitrate")).toBe("192");
    expect(value(w, "audio-rate")).toBe("48000");
    expect((w.get('[data-test="two-pass"]').element as HTMLInputElement).checked).toBe(true);
    expect([value(w, "lufs"), value(w, "true-peak"), value(w, "lra")]).toEqual(["-18", "-1.5", "11"]);
    expect([value(w, "fade-in"), value(w, "fade-out")]).toEqual(["1", "1.5"]);
    expect([value(w, "intro"), value(w, "outro")]).toEqual(["treebu-hotels-intro.mp4", "treebu-hotels-intro.mp4"]);
    expect([value(w, "intro-transition"), value(w, "outro-transition")]).toEqual(["1", "1"]);
  });

  it("round-trips the production profile unchanged, with no keys added or dropped", async () => {
    const update = vi
      .spyOn(ui.procProfiles, "update")
      .mockResolvedValue({ profile: productionProfile, affected_clip_ids: [] });
    const w = mount(ProcessingProfileForm, { props: { profile: productionProfile } });
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(update).toHaveBeenCalledExactlyOnceWith("4k-loudness-with-intro", {
      name: "4K con intro y audio normalizado",
      settings: productionProfile.settings,
    });
    expect(w.emitted("saved")).toHaveLength(1);
    update.mockRestore();
  });

  it.each([
    ["4k", 3840, 2160],
    ["1080p", 1920, 1080],
    ["720p", 1280, 720],
  ])("maps the %s preset to %i x %i for the video size and the scaling width and height", async (preset, width, height) => {
    const w = mount(ProcessingProfileForm, { props: { profile: productionProfile } });
    await w.get('[data-test="resolution"]').setValue(preset === "4k" ? "720p" : "4k");
    await w.get('[data-test="resolution"]').setValue(preset);
    const { video } = jsonOf(w);
    expect([video.width, video.height]).toEqual([width, height]);
    expect([video.scaling.width, video.scaling.height]).toEqual([width, height]);
    expect(video.scaling.strategy).toBe("aspect_fit");
  });

  it("offers a custom resolution entry when the size matches no preset", () => {
    const profile = clone(productionProfile);
    profile.settings.video.width = 2560;
    profile.settings.video.height = 1440;
    const w = mount(ProcessingProfileForm, { props: { profile } });
    expect(value(w, "resolution")).toBe("custom");
    expect(w.get('[data-test="resolution"]').text()).toContain("2560 × 1440");
  });

  it("edits video, audio, fade and loudness numbers into the settings", async () => {
    const w = mount(ProcessingProfileForm, { props: { profile: productionProfile } });
    await w.get('[data-test="fps"]').setValue("30");
    await w.get('[data-test="crf"]').setValue("20");
    await w.get('[data-test="maxrate"]').setValue("");
    await w.get('[data-test="audio-bitrate"]').setValue("256");
    await w.get('[data-test="audio-rate"]').setValue("44100");
    await w.get('[data-test="lufs"]').setValue("-16");
    await w.get('[data-test="fade-in"]').setValue("0.5");
    const settings = jsonOf(w);
    expect(settings.video.fps).toBe(30);
    expect(settings.video.quality).toEqual({ mode: "crf", crf: 20 });
    expect(settings.video.maxrate_kbps).toBeNull();
    expect(settings.audio.bitrate_kbps).toBe(256);
    expect(settings.audio.sample_rate).toBe(44100);
    expect(settings.loudness).toMatchObject({ mode: "two_pass", integrated_lufs: -16, true_peak_dbtp: -1.5 });
    expect(settings.fade_in_seconds).toBe(0.5);
  });

  it("switches two-pass loudness off and back on, remembering the targets", async () => {
    const w = mount(ProcessingProfileForm, { props: { profile: productionProfile } });
    await w.get('[data-test="lufs"]').setValue("-14");
    await w.get('[data-test="two-pass"]').setValue(false);
    expect(jsonOf(w).loudness).toEqual({ mode: "disabled", final_mix_normalization: true });
    expect(w.find('[data-test="lufs"]').exists()).toBe(false);
    await w.get('[data-test="two-pass"]').setValue(true);
    expect(jsonOf(w).loudness).toEqual({
      mode: "two_pass", integrated_lufs: -14, true_peak_dbtp: -1.5, lra_lu: 11, final_mix_normalization: true,
    });
  });

  it("selects intro and outro assets and keeps the transitions in step", async () => {
    const w = mount(ProcessingProfileForm, { props: { profile: productionProfile } });
    await w.get('[data-test="intro"]').setValue("other.mp4");
    await w.get('[data-test="intro-transition"]').setValue("2");
    await w.get('[data-test="outro"]').setValue("");
    let settings = jsonOf(w);
    expect(settings.intro_reference).toBe("other.mp4");
    expect(settings.outro_reference).toBeNull();
    expect(settings.transitions).toEqual([
      { duration_seconds: 2, from_segment: "intro", to_segment: "clip", type: "fade" },
    ]);
    expect(w.get('[data-test="outro-transition"]').attributes("disabled")).toBeDefined();
    await w.get('[data-test="outro"]').setValue("other.mp4");
    await w.get('[data-test="outro-transition"]').setValue("1.5");
    settings = jsonOf(w);
    expect(settings.transitions.at(-1)).toEqual({
      duration_seconds: 1.5, from_segment: "clip", to_segment: "outro", type: "fade",
    });
  });

  it("keeps an intro that is no longer an uploaded asset selectable and marks it missing", () => {
    const profile = clone(productionProfile);
    profile.settings.intro_reference = "gone.mp4";
    const w = mount(ProcessingProfileForm, { props: { profile } });
    expect(value(w, "intro")).toBe("gone.mp4");
    expect(w.get('[data-test="intro"]').text()).toContain("gone.mp4 (missing)");
  });

  it("applies Advanced JSON edits to the structured fields and saves them", async () => {
    const update = vi.spyOn(ui.procProfiles, "update").mockResolvedValue({
      profile: productionProfile, affected_clip_ids: [],
    });
    const w = mount(ProcessingProfileForm, { props: { profile: productionProfile } });
    const edited = clone(productionProfile.settings);
    edited.video.fps = 60;
    edited.video.width = 2560;
    edited.video.height = 1440;
    await w.get('[data-test="json"]').setValue(JSON.stringify(edited));
    expect(value(w, "fps")).toBe("60");
    expect(value(w, "resolution")).toBe("custom");
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(update).toHaveBeenCalledWith("4k-loudness-with-intro", { name: productionProfile.name, settings: edited });
    update.mockRestore();
  });

  it("does not rewrite the JSON text while it is being typed", async () => {
    const w = mount(ProcessingProfileForm, { props: { profile: productionProfile } });
    const compact = JSON.stringify(productionProfile.settings);
    await w.get('[data-test="json"]').setValue(compact);
    expect((w.get('[data-test="json"]').element as HTMLTextAreaElement).value).toBe(compact);
  });

  it("blocks saving invalid JSON and says why", async () => {
    const create = vi.spyOn(ui.procProfiles, "create");
    const w = mount(ProcessingProfileForm);
    await w.get('[data-test="name"]').setValue("Broken");
    await w.get('[data-test="json"]').setValue("{ nope");
    expect(w.get('[data-test="json-error"]').text()).toBe("Advanced JSON is not valid JSON.");
    await w.get("form").trigger("submit");
    expect(create).not.toHaveBeenCalled();
    await w.get('[data-test="json"]').setValue("[1]");
    expect(w.get('[data-test="json-error"]').text()).toBe("Advanced JSON must be an object.");
    create.mockRestore();
  });

  it("creates a profile from the defaults (4K, two-pass loudness) and requires a name", async () => {
    const create = vi.spyOn(ui.procProfiles, "create").mockImplementation(async (body) => saved(body.settings));
    const w = mount(ProcessingProfileForm);
    await w.get("form").trigger("submit");
    expect(create).not.toHaveBeenCalled();
    expect(w.get('[role="alert"]').text()).toBe("Enter a name.");
    expect(value(w, "resolution")).toBe("4k");
    await w.get('[data-test="name"]').setValue("Mine");
    await w.get("form").trigger("submit");
    await flushPromises();
    const body = create.mock.calls[0]![0];
    expect(body.name).toBe("Mine");
    expect(body.settings.video).toMatchObject({ width: 3840, height: 2160, fps: 24 });
    expect(body.settings.loudness.mode).toBe("two_pass");
    expect(body.settings.profile_version).toBe(1);
    expect(w.emitted("saved")).toHaveLength(1);
    create.mockRestore();
  });

  it("shows the server's validation message and does not leave the form", async () => {
    const update = vi
      .spyOn(ui.procProfiles, "update")
      .mockRejectedValue(new Error("video.fps: Input should be greater than 0"));
    const w = mount(ProcessingProfileForm, { props: { profile: productionProfile } });
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(w.get('[role="alert"]').text()).toBe("video.fps: Input should be greater than 0");
    expect(w.emitted("saved")).toBeUndefined();
    update.mockRestore();
  });

  it("toasts how many clips are re-rendered after changing an existing profile", async () => {
    const update = vi.spyOn(ui.procProfiles, "update").mockResolvedValue({
      profile: productionProfile, affected_clip_ids: ["a", "b", "c"],
    });
    const w = mount(ProcessingProfileForm, { props: { profile: productionProfile } });
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(useToast().toasts.value.map((t) => t.message)).toContain("3 clips will be re-rendered");
    update.mockRestore();
  });

  it("switches to update mode after a create so a retry cannot create a duplicate", async () => {
    const create = vi.spyOn(ui.procProfiles, "create").mockImplementation(async (body) => saved(body.settings, "new-id"));
    const update = vi.spyOn(ui.procProfiles, "update").mockResolvedValue({
      profile: saved(productionProfile.settings, "new-id"), affected_clip_ids: [],
    });
    vi.mocked(useStudio().refresh).mockRejectedValueOnce(new Error("offline"));
    const w = mount(ProcessingProfileForm);
    await w.get('[data-test="name"]').setValue("Once");
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(create).toHaveBeenCalledTimes(1);
    expect(w.emitted("saved")).toHaveLength(1);
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(create).toHaveBeenCalledTimes(1);
    create.mockRestore();
    update.mockRestore();
  });
});
