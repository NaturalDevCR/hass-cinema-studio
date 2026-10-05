vi.mock("@/composables/useUpload", async (original) => {
  const actual = await original<typeof import("@/composables/useUpload")>();
  const start = vi.fn().mockResolvedValue(undefined);
  return { ...actual, useUpload: () => ({ ...actual.useUpload(), start }) };
});
vi.mock("@/composables/useStudio", async (original) => {
  const actual = await original<typeof import("@/composables/useStudio")>();
  return { ...actual, useStudio: () => ({ ...actual.useStudio(), refresh: vi.fn(), refreshClips: vi.fn() }) };
});
import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import UploadView from "./UploadView.vue";
import { useUpload } from "@/composables/useUpload";
import { useStudio } from "@/composables/useStudio";
import { useI18n } from "@/i18n";
import { createAppRouter } from "@/router";
import { makeCollection } from "@/test/factories";

const wrappers: ReturnType<typeof mount>[] = [];
beforeEach(() => {
  vi.clearAllMocks();
  useUpload().busy.value = false;
  useUpload().items.value = [];
  useI18n().setLocale("en");
  useStudio().loaded.value = true;
  useStudio().collections.value = [
    makeCollection({ id: "regular", name: "Regular" }),
    makeCollection({ id: "horror", name: "Horror" }),
  ];
});
afterEach(() => {
  wrappers.splice(0).forEach((w) => w.unmount());
});
async function mountView() {
  const router = createAppRouter(createMemoryHistory());
  await router.push("/upload");
  await router.isReady();
  const w = mount(UploadView, { global: { plugins: [router] } });
  wrappers.push(w);
  return { w, router };
}

it("offers only the collection as a batch default and summarizes it when collapsed", async () => {
  const { w } = await mountView();
  expect(w.findAll("#upload-defaults select")).toHaveLength(1);
  expect(w.get('[data-test="defaults-summary"]').text()).toBe("Regular");
  await w.get("#upload-collection").setValue("horror");
  expect((w.get("#upload-collection").element as HTMLSelectElement).value).toBe("horror");
  await w.get('[aria-controls="upload-defaults"]').trigger("click");
  expect(w.find('[data-test="defaults-summary"]').exists()).toBe(false);
});

it("starts the batch with the collection id only, and no season, tag or profile fields", async () => {
  const { w } = await mountView();
  useUpload().add([new File(["video"], "trailer.mp4")]);
  await w.get("#upload-collection").setValue("horror");
  await w.vm.$nextTick();
  await w.get('[data-test="upload-bar"] button').trigger("click");
  expect(useUpload().start).toHaveBeenCalledExactlyOnceWith({ collection_id: "horror" });
});

it("only displays the sticky bar while files are queued and leaves measured clearance", async () => {
  const { w } = await mountView();
  expect(w.find('[data-test="upload-bar"]').exists()).toBe(false);
  useUpload().add([new File(["video"], "trailer.mp4")]);
  await w.vm.$nextTick();
  const bar = w.get('[data-test="upload-bar"]');
  expect(bar.classes()).toContain("bottom-[var(--tabbar-h)]");
  expect(w.get('[data-test="upload-bar"] button').text()).toBe("Upload 1 file");
  useUpload().remove(useUpload().items.value[0]!.id);
  await w.vm.$nextTick();
  expect(w.find('[data-test="upload-bar"]').exists()).toBe(false);
});

it("labels the sticky bar Processing… when only processing rows remain", async () => {
  const { w } = await mountView();
  useUpload().add([new File(["video"], "trailer.mp4")]);
  useUpload().items.value[0]!.status = "processing";
  await w.vm.$nextTick();
  expect(w.get('[data-test="upload-bar"] button').text()).toBe("Processing…");
});

it("links finished rows to the clip editor", async () => {
  const { w } = await mountView();
  useUpload().add([new File(["video"], "trailer.mp4")]);
  const item = useUpload().items.value[0]!;
  item.status = "done";
  item.clipId = "clip-9";
  await w.vm.$nextTick();
  expect(w.get("li a").attributes("href")).toBe("/clips/clip-9");
});

it("asks to create a collection first when none exists", async () => {
  useStudio().collections.value = [];
  const { w } = await mountView();
  expect(w.text()).toContain("Create a collection");
  useUpload().add([new File(["video"], "trailer.mp4")]);
  await w.vm.$nextTick();
  expect(w.get('[data-test="upload-bar"] button').attributes("disabled")).toBeDefined();
  expect(w.get('[data-test="upload-bar"] [role="alert"]').text()).toBe("Choose a collection for this batch.");
});

it("hides retry for validation failures but keeps it for failed transfers", async () => {
  const { w } = await mountView();
  useUpload().add([new File(["x"], "bad.exe"), new File([], "empty.mp4")]);
  await w.vm.$nextTick();
  expect(w.findAll('button[aria-label^="Retry"]')).toHaveLength(0);
  useUpload().add([new File(["x"], "retry.mp4")]);
  const item = useUpload().items.value.at(-1)!;
  item.status = "error";
  item.error = "Offline";
  await w.vm.$nextTick();
  expect(w.findAll('button[aria-label^="Retry"]')).toHaveLength(1);
});
