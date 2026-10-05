import { mount, flushPromises } from "@vue/test-utils";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import { defineComponent, h } from "vue";
import { createRouter, createMemoryHistory, RouterView } from "vue-router";
import ClipEditorView from "./ClipEditorView.vue";
import { makeClip } from "@/test/factories";
import { makeState } from "@/test/system";
import { useStudio } from "@/composables/useStudio";
import { useJobs } from "@/composables/useJobs";
import { useConfirm } from "@/composables/useConfirm";
import type { Job } from "@/api/types";
import { useI18n } from "@/i18n";
const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  list: vi.fn(),
  putRecipe: vi.fn(),
  test: vi.fn(),
  preview: vi.fn(),
  update: vi.fn(),
  replaceSource: vi.fn(),
  jobs: vi.fn(),
  uploads: { create: vi.fn(), chunk: vi.fn() },
}));
vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  api: vi
    .fn()
    .mockResolvedValue({ interval: 2, count: 0, width: 160, height: 90 }),
  ui: { clips: mocks, jobs: mocks.jobs, uploads: mocks.uploads },
}));
let wrapper: ReturnType<typeof mount>;
let activeRouter: ReturnType<typeof createRouter>;
const previewJob: Job = {
  id: "preview-job",
  kind: "preview",
  clip_id: "a",
  clip_title: "a",
  status: "done",
  progress: 1,
  error: null,
  created_at: "",
  started_at: null,
  finished_at: null,
};
beforeEach(() => {
  vi.clearAllMocks();
  useJobs().jobs.value = [];
  mocks.jobs.mockResolvedValue([]);
  mocks.list.mockResolvedValue([makeClip({ id: "a" })]);
  useI18n().setLocale("en");
  useStudio().state.value = {
    ...makeState(),
    settings: {
      ...makeState().settings,
      test_targets: [
        { id: "tv", label: "TV", entity_id: "media_player.tv" },
        { id: "tv2", label: "Second TV", entity_id: "media_player.tv2" },
      ],
    },
  };
  mocks.get.mockResolvedValue(makeClip({ id: "a" }));
  mocks.putRecipe.mockImplementation(async (_id, recipe) => ({
    clip: makeClip({ id: "a", recipe }),
    job: {},
  }));
  mocks.test.mockResolvedValue({ ok: true });
});
afterEach(() => {
  useConfirm().answer(false);
  wrapper?.unmount();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});
async function setup() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/clips/:id", component: ClipEditorView, props: true },
      { path: "/", name: "library", component: { template: "<div />" } },
      { path: "/system", component: { template: "<div />" } },
    ],
  });
  activeRouter = router;
  await router.push("/clips/a");
  await router.isReady();
  wrapper = mount(defineComponent({ render: () => h(RouterView) }), {
    global: { plugins: [router], stubs: { teleport: true } },
  });
  await flushPromises();
  return wrapper;
}
it("saves changed trim and source-pixel crop only", async () => {
  const w = await setup();
  expect(w.get("[data-test=save]").attributes("disabled")).toBeDefined();
  await w.get("[data-test=trim-start]").setValue("00:00:01.000");
  expect(w.get("[data-test=save]").attributes("disabled")).toBeUndefined();
  w.getComponent({ name: "CropOverlay" }).vm.$emit("update:modelValue", {
    x: 100,
    y: 200,
    w: 800,
    h: 600,
  });
  await w.get("[data-test=save]").trigger("click");
  await flushPromises();
  expect(mocks.putRecipe).toHaveBeenCalledWith(
    "a",
    expect.objectContaining({
      trim_start: 1,
      crop: { x: 100, y: 200, w: 800, h: 600 },
    }),
  );
});
it("rejects inverted trim", async () => {
  const w = await setup();
  await w.get("[data-test=trim-start]").setValue("00:00:15.000");
  expect(w.get("[role=alert]").text()).toBeTruthy();
  expect(w.get("[data-test=save]").attributes("disabled")).toBeDefined();
});
it("tests the selected device and source", async () => {
  const w = await setup();
  await w.get("[data-test=test-device]").trigger("click");
  await w.get("[data-test=test-target]").setValue("tv2");
  await w.get("[data-test=send-test]").trigger("click");
  await flushPromises();
  expect(mocks.test).toHaveBeenCalledWith("a", {
    target_id: "tv2",
    source: "render",
  });
});

it("nudges trim by frames, with shift tenfold", async () => {
  const w = await setup();
  const handle = w.get('[role=slider][aria-label="Trim start"]');
  await handle.trigger("keydown", { key: "ArrowRight" });
  await handle.trigger("keydown", { key: "ArrowRight", shiftKey: true });
  await w.get("[data-test=save]").trigger("click");
  await flushPromises();
  expect(mocks.putRecipe).toHaveBeenCalledWith(
    "a",
    expect.objectContaining({ trim_start: 11 / 24 }),
  );
});
it("keeps invalid text visible and blocks saving", async () => {
  const w = await setup();
  await w.get("[data-test=trim-start]").setValue("bad");
  expect(w.get("[role=alert]").text()).toContain("HH:MM:SS");
  expect(w.get("[data-test=save]").attributes("disabled")).toBeDefined();
  expect(
    (w.get("[data-test=trim-start]").element as HTMLInputElement).value,
  ).toBe("bad");
});
it("shows server recipe validation failures without losing the draft", async () => {
  mocks.putRecipe.mockRejectedValue(new Error("Crop rejected"));
  const w = await setup();
  await w.get("[data-test=trim-start]").setValue("1");
  await w.get("[data-test=save]").trigger("click");
  await flushPromises();
  expect(w.get("[role=alert]").text()).toBe("Crop rejected");
  expect(w.get("[data-test=save]").attributes("disabled")).toBeUndefined();
});
it("filters protected and non-media-player targets", async () => {
  const w = await setup();
  useStudio().state.value!.settings.test_targets = [
    {
      id: "protected",
      label: "Protected",
      entity_id: "media_player.otocuma_dp",
    },
    { id: "cover", label: "Cover", entity_id: "cover.screen" },
  ];
  await w.get("[data-test=test-device]").trigger("click");
  expect(w.text()).toContain("No test devices");
  expect(w.get("[data-test=send-test]").attributes("disabled")).toBeDefined();
  expect(mocks.test).not.toHaveBeenCalled();
});
it("plays a completed preview and invalidates it on further edits", async () => {
  mocks.preview.mockResolvedValue({ job: previewJob });
  mocks.jobs.mockResolvedValue([previewJob]);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  const w = await setup();
  await w.get("[data-test=trim-start]").setValue("1");
  await w.get("[data-test=preview-render]").trigger("click");
  await flushPromises();
  expect(mocks.preview).toHaveBeenCalledWith(
    "a",
    expect.objectContaining({ trim_start: 1 }),
  );
  expect(w.get("video").attributes("src")).toContain("/preview?v=preview-job");
  await w.get("[data-test=trim-start]").setValue("2");
  await flushPromises();
  expect(w.get("video").attributes("src")).toContain("/original");
});
it("ignores a completed preview of an older recipe", async () => {
  let resolve!: (value: { job: Job }) => void;
  mocks.preview.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  mocks.jobs.mockResolvedValue([previewJob]);
  const w = await setup();
  await w.get("[data-test=preview-render]").trigger("click");
  await w.get("[data-test=trim-start]").setValue("2");
  resolve({ job: previewJob });
  await flushPromises();
  expect(w.get("video").attributes("src")).toContain("/original");
});
it("keeps the draft during catalog refreshes", async () => {
  const w = await setup();
  await w.get("[data-test=trim-start]").setValue("1");
  useStudio().clips.value = [
    makeClip({ id: "a", status: "rendering", render_pending: true }),
  ];
  await flushPromises();
  await w.get("[data-test=save]").trigger("click");
  await flushPromises();
  expect(mocks.putRecipe).toHaveBeenCalledWith(
    "a",
    expect.objectContaining({ trim_start: 1 }),
  );
  expect(w.get("[data-test=save]").attributes("disabled")).toBeDefined();
});
it("guards navigation and supports cancellation", async () => {
  const w = await setup();
  await w.get("[data-test=trim-start]").setValue("1");
  const navigation = activeRouter.push("/");
  await flushPromises();
  expect(useConfirm().request.value?.title).toBe("Discard unsaved changes?");
  useConfirm().answer(false);
  await navigation;
  expect(activeRouter.currentRoute.value.path).toBe("/clips/a");
});
it("repairs source with chunk upload, without completing a new clip", async () => {
  mocks.get.mockResolvedValue(
    makeClip({ id: "a", needs_source: true, original: null }),
  );
  mocks.uploads.create.mockResolvedValue({
    upload_id: "upload-1",
    chunk_size: 2,
  });
  mocks.uploads.chunk.mockResolvedValue({ received: 2 });
  mocks.replaceSource.mockResolvedValue(makeClip({ id: "a" }));
  // Repair refreshes only the shared clips list and jobs.
  const w = await setup();
  const input = w.get("input[type=file]");
  const file = new File(["12345"], "source.mp4");
  Object.defineProperty(input.element, "files", {
    value: [file],
    configurable: true,
  });
  await input.trigger("change");
  await flushPromises();
  expect(
    mocks.uploads.chunk.mock.calls.map((c) => [
      c[0],
      c[1],
      (c[2] as Blob).size,
    ]),
  ).toEqual([
    ["upload-1", 0, 2],
    ["upload-1", 1, 2],
    ["upload-1", 2, 1],
  ]);
  expect(mocks.replaceSource).toHaveBeenCalledWith("a", "upload-1");
  expect(w.find("input[type=file]").exists()).toBe(false);
});
