vi.mock("@/composables/useStudio", async (original) => {
  const actual = await original<typeof import("@/composables/useStudio")>();
  const refresh = vi.fn().mockResolvedValue(undefined);
  return { ...actual, useStudio: () => ({ ...actual.useStudio(), refresh }) };
});
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AssetsPanel from "./AssetsPanel.vue";
import { ApiError, ui } from "@/api/client";
import type { Asset } from "@/api/types";
import { useConfirm } from "@/composables/useConfirm";
import { useStudio } from "@/composables/useStudio";
import { useToast } from "@/composables/useToast";
import { useI18n } from "@/i18n";

const ready: Asset = { filename: "intro.mp4", size: 2 * 1024 * 1024, sha256: "a".repeat(64), status: "ready" };
const missing: Asset = { filename: "outro.mp4", size: null, sha256: null, status: "missing" };
const choose = async (input: ReturnType<ReturnType<typeof mount>["get"]>, ...files: File[]) => {
  Object.defineProperty(input.element, "files", { value: files, configurable: true });
  await input.trigger("change");
  await flushPromises();
};

beforeEach(() => {
  vi.mocked(useStudio().refresh).mockClear();
  useI18n().setLocale("en");
  useToast().toasts.value = [];
  useStudio().assets.value = [ready, missing];
});
afterEach(() => {
  useConfirm().answer(false);
  vi.restoreAllMocks();
});

describe("AssetsPanel", () => {
  it("lists assets with their ready or missing status and size", () => {
    const w = mount(AssetsPanel);
    const rows = w.findAll("li");
    expect(rows).toHaveLength(2);
    expect(rows[0]!.text()).toContain("intro.mp4");
    expect(rows[0]!.text()).toContain("2.0 MB");
    expect(rows[0]!.get('[data-status="ready"]').text()).toBe("Ready");
    expect(rows[1]!.get('[data-status="missing"]').text()).toBe("Missing");
  });

  it("highlights a missing asset with an Upload <filename> call to action", () => {
    const w = mount(AssetsPanel);
    const row = w.findAll("li")[1]!;
    expect(row.attributes("data-missing")).toBe("true");
    expect(row.get('[data-test="upload-missing"]').text()).toBe("Upload outro.mp4");
    expect(w.findAll("li")[0]!.find('[data-test="upload-missing"]').exists()).toBe(false);
  });

  it("uploads a new asset and tells how many clips are re-rendered", async () => {
    const upload = vi.spyOn(ui.assets, "upload").mockResolvedValue({ asset: ready, affected_clip_ids: ["a", "b"] });
    const w = mount(AssetsPanel);
    const file = new File(["x"], "new-intro.mp4");
    await choose(w.get('[data-test="asset-input"]'), file);
    expect(upload).toHaveBeenCalledExactlyOnceWith(file);
    expect(useStudio().refresh).toHaveBeenCalled();
    expect(useToast().toasts.value.map((t) => t.message)).toEqual(["Saved", "2 clips will be re-rendered"]);
  });

  it("uploads the missing file from its call to action", async () => {
    const upload = vi.spyOn(ui.assets, "upload").mockResolvedValue({ asset: ready, affected_clip_ids: [] });
    const w = mount(AssetsPanel);
    const file = new File(["x"], "outro.mp4");
    await choose(w.get('[data-test="missing-input"]'), file);
    expect(upload).toHaveBeenCalledExactlyOnceWith(file);
  });

  it("refuses a file named differently from the missing asset", async () => {
    const upload = vi.spyOn(ui.assets, "upload");
    const w = mount(AssetsPanel);
    await choose(w.get('[data-test="missing-input"]'), new File(["x"], "something-else.mp4"));
    expect(upload).not.toHaveBeenCalled();
    expect(w.get('[data-test="assets-error"]').text()).toBe("Choose a file named outro.mp4.");
  });

  it("rejects unsupported file types before uploading", async () => {
    const upload = vi.spyOn(ui.assets, "upload");
    const w = mount(AssetsPanel);
    await choose(w.get('[data-test="asset-input"]'), new File(["x"], "notes.txt"));
    expect(upload).not.toHaveBeenCalled();
    expect(w.get('[data-test="assets-error"]').text()).toBe("This file type is not supported.");
  });

  it("shows upload failures inline", async () => {
    vi.spyOn(ui.assets, "upload").mockRejectedValue(new ApiError(413, "File too large"));
    const w = mount(AssetsPanel);
    await choose(w.get('[data-test="asset-input"]'), new File(["x"], "big.mp4"));
    expect(w.get('[data-test="assets-error"]').text()).toBe("File too large");
  });

  it("confirms deletion, then deletes and refreshes", async () => {
    const remove = vi.spyOn(ui.assets, "remove").mockResolvedValue(undefined);
    const w = mount(AssetsPanel);
    await w.get('button[aria-label="Delete intro.mp4"]').trigger("click");
    expect(useConfirm().request.value?.danger).toBe(true);
    expect(remove).not.toHaveBeenCalled();
    useConfirm().answer(true);
    await flushPromises();
    expect(remove).toHaveBeenCalledExactlyOnceWith("intro.mp4");
    expect(useStudio().refresh).toHaveBeenCalled();
  });

  it("does not delete when the confirmation is declined", async () => {
    const remove = vi.spyOn(ui.assets, "remove");
    const w = mount(AssetsPanel);
    await w.get('button[aria-label="Delete intro.mp4"]').trigger("click");
    useConfirm().answer(false);
    await flushPromises();
    expect(remove).not.toHaveBeenCalled();
  });

  it("explains that an asset still used by a profile cannot be deleted", async () => {
    vi.spyOn(ui.assets, "remove").mockRejectedValue(new ApiError(409, "Asset is referenced by a profile"));
    const w = mount(AssetsPanel);
    await w.get('button[aria-label="Delete intro.mp4"]').trigger("click");
    useConfirm().answer(true);
    await flushPromises();
    expect(w.get('[data-test="assets-error"]').text()).toBe(
      "This asset is used by a processing profile. Remove it from the profile first.",
    );
  });

  it("shows an empty state with an upload button when there are no assets", () => {
    useStudio().assets.value = [];
    const w = mount(AssetsPanel);
    expect(w.text()).toContain("No intro or outro assets yet");
    expect(w.findAll("li")).toHaveLength(0);
  });
});
