import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { createMemoryHistory, RouterView } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useConfirm } from "@/composables/useConfirm";
import { usePlayer } from "@/composables/usePlayer";
import { useStudio } from "@/composables/useStudio";
import { useI18n } from "@/i18n";
import { createAppRouter } from "@/router";
import { makeClip, makeCollection, makeNormProfile } from "@/test/factories";
import { makeState } from "@/test/system";

const mocks = vi.hoisted(() => ({
  ui: {
    state: vi.fn(),
    collections: { list: vi.fn() },
    seasons: { list: vi.fn() },
    normProfiles: { list: vi.fn(), apply: vi.fn() },
    procProfiles: { list: vi.fn() },
    assets: { list: vi.fn() },
    clips: { list: vi.fn(), bulk: vi.fn(), rerender: vi.fn(), remove: vi.fn() },
  },
}));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ui: mocks.ui,
}));


const clips = [makeClip({ id: "a", title: "Alpha" }), makeClip({ id: "b", title: "Beta" }), makeClip({ id: "c", title: "Gamma", collection_id: "other" })];

async function mountLibrary(path = "/") {
  const router = createAppRouter(createMemoryHistory());
  await router.push(path);
  await router.isReady();
  // Mount through a RouterView so the view's own nested <RouterView /> sits at depth 1, as in the app.
  const wrapper = mount(defineComponent({ render: () => h(RouterView) }), { attachTo: document.body, global: { plugins: [router] } });
  await useStudio().refresh();
  await flushPromises();
  return { wrapper, router };
}

async function select(wrapper: ReturnType<typeof mount>, ...titles: string[]) {
  for (const title of titles) await wrapper.get(`[aria-label="Select ${title}"]`).trigger("click");
}

beforeEach(() => {
  vi.clearAllMocks();
  useI18n().setLocale("en");
  mocks.ui.state.mockResolvedValue(makeState());
  mocks.ui.collections.list.mockResolvedValue([makeCollection({ id: "regular" }), makeCollection({ id: "other", playback_mode: "sequential" })]);
  mocks.ui.seasons.list.mockResolvedValue([]);
  mocks.ui.normProfiles.list.mockResolvedValue([makeNormProfile({ id: "loud" })]);
  mocks.ui.procProfiles.list.mockResolvedValue([]);
  mocks.ui.assets.list.mockResolvedValue([]);
  mocks.ui.clips.list.mockResolvedValue(clips);
  mocks.ui.clips.bulk.mockResolvedValue({ updated: 2, queued: 0 });
  mocks.ui.clips.rerender.mockResolvedValue({});
  mocks.ui.clips.remove.mockResolvedValue(undefined);
  mocks.ui.normProfiles.apply.mockResolvedValue({ queued: 2 });
});
afterEach(() => { usePlayer().stop(); document.body.innerHTML = ""; vi.useRealTimers(); });

describe("LibraryView search", () => {
  it("does not overwrite typed text when another filter changes the route during the debounce", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { wrapper, router } = await mountLibrary();
    const input = wrapper.get('input[type="search"]');
    await input.setValue("alp");
    // Another filter updates the route before the 150 ms debounce has fired.
    await wrapper.get('select[aria-label="Filter by status"]').setValue("ready");
    await flushPromises();
    expect((input.element as HTMLInputElement).value).toBe("alp");
    expect(router.currentRoute.value.query.status).toBe("ready");
    vi.advanceTimersByTime(200);
    await flushPromises();
    expect(router.currentRoute.value.query).toMatchObject({ q: "alp", status: "ready" });
    expect((input.element as HTMLInputElement).value).toBe("alp");
    expect(wrapper.findAll('[data-test="open"]').map((b) => b.get("span").text())).toEqual(["Alpha"]);
  });

  it("applies the search to the URL after the 150 ms debounce and follows external navigation", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { wrapper, router } = await mountLibrary();
    await wrapper.get('input[type="search"]').setValue("beta");
    expect(router.currentRoute.value.query.q).toBeUndefined();
    vi.advanceTimersByTime(150);
    await flushPromises();
    expect(router.currentRoute.value.query.q).toBe("beta");
    await router.replace({ query: { q: "gamma" } });
    await flushPromises();
    expect((wrapper.get('input[type="search"]').element as HTMLInputElement).value).toBe("gamma");
  });
});

describe("LibraryView bulk actions", () => {
  it("moves the selection to a collection", async () => {
    const { wrapper } = await mountLibrary();
    await select(wrapper, "Alpha", "Beta");
    await wrapper.get('[data-test="action-move"]').trigger("click");
    await flushPromises();
    await document.body.querySelector<HTMLSelectElement>("[role=dialog] select")!.dispatchEvent(new Event("change"));
    const confirm = [...document.body.querySelectorAll<HTMLButtonElement>("[role=dialog] button")].find((b) => b.textContent?.trim() === "Confirm")!;
    confirm.click();
    await flushPromises();
    expect(mocks.ui.clips.bulk).toHaveBeenCalledWith({ ids: ["a", "b"], set: { collection_id: "regular" } });
    expect(mocks.ui.clips.list).toHaveBeenCalledTimes(2);
  });

  it.each([["enable", true], ["disable", false]] as const)("%s sets enabled through bulk", async (action, enabled) => {
    const { wrapper } = await mountLibrary();
    await select(wrapper, "Alpha", "Beta");
    await wrapper.get(`[data-test="action-${action}"]`).trigger("click");
    await flushPromises();
    expect(mocks.ui.clips.bulk).toHaveBeenCalledWith({ ids: ["a", "b"], set: { enabled } });
  });

  it("normalizes the selection with a profile, and clears the profile for None", async () => {
    const { wrapper } = await mountLibrary();
    await select(wrapper, "Alpha", "Beta");
    await wrapper.get('[data-test="action-normalize"]').trigger("click");
    await flushPromises();
    const dialogSelect = () => document.body.querySelector<HTMLSelectElement>("[role=dialog] select")!;
    const confirm = () => [...document.body.querySelectorAll<HTMLButtonElement>("[role=dialog] button")].find((b) => b.textContent?.trim() === "Confirm")!;
    dialogSelect().value = "loud";
    dialogSelect().dispatchEvent(new Event("change"));
    await flushPromises();
    confirm().click();
    await flushPromises();
    expect(mocks.ui.normProfiles.apply).toHaveBeenCalledWith("loud", { clip_ids: ["a", "b"] });

    await select(wrapper, "Alpha", "Beta");
    await wrapper.get('[data-test="action-normalize"]').trigger("click");
    await flushPromises();
    confirm().click();
    await flushPromises();
    expect(mocks.ui.clips.bulk).toHaveBeenCalledWith({ ids: ["a", "b"], set: { profile_id: null } });
  });

  it("re-renders each selected clip", async () => {
    const { wrapper } = await mountLibrary();
    await select(wrapper, "Alpha", "Beta");
    await wrapper.get('[data-test="action-rerender"]').trigger("click");
    await flushPromises();
    expect(mocks.ui.clips.rerender.mock.calls.map((c) => c[0])).toEqual(["a", "b"]);
  });

  it("deletes only after confirmation", async () => {
    const { wrapper } = await mountLibrary();
    await select(wrapper, "Alpha", "Beta");
    const pending = wrapper.get('[data-test="action-delete"]').trigger("click");
    await flushPromises();
    expect(useConfirm().request.value?.danger).toBe(true);
    useConfirm().answer(false);
    await pending;
    await flushPromises();
    expect(mocks.ui.clips.remove).not.toHaveBeenCalled();

    await wrapper.get('[data-test="action-delete"]').trigger("click");
    await flushPromises();
    useConfirm().answer(true);
    await flushPromises();
    expect(mocks.ui.clips.remove.mock.calls.map((c) => c[0])).toEqual(["a", "b"]);
    expect(wrapper.find('[role="toolbar"]').exists()).toBe(false);
  });
});
