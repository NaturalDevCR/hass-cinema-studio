import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeState } from "@/test/system";
import { useI18n } from "@/i18n";
import { createAppRouter } from "@/router";

const mocks = vi.hoisted(() => ({
  ui: {
    state: vi.fn(),
    collections: { list: vi.fn() },
    seasons: { list: vi.fn() },
    normProfiles: { list: vi.fn() },
    procProfiles: { list: vi.fn() },
    assets: { list: vi.fn() },
    clips: { list: vi.fn() },
    jobs: vi.fn(),
  },
}));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ui: mocks.ui,
}));

import App from "@/App.vue";
import { useJobs } from "@/composables/useJobs";
import { useStudio } from "@/composables/useStudio";

async function mountApp(path = "/") {
  const router = createAppRouter(createMemoryHistory());
  await router.push(path);
  await router.isReady();
  const wrapper = mount(App, { attachTo: document.body, global: { plugins: [router] } });
  await flushPromises();
  return { wrapper, router };
}

beforeEach(() => {
  useI18n().setLocale("en");
  vi.clearAllMocks();
  mocks.ui.state.mockResolvedValue(makeState());
  mocks.ui.collections.list.mockResolvedValue([]);
  mocks.ui.seasons.list.mockResolvedValue([]);
  mocks.ui.normProfiles.list.mockResolvedValue([]);
  mocks.ui.procProfiles.list.mockResolvedValue([]);
  mocks.ui.assets.list.mockResolvedValue([]);
  mocks.ui.clips.list.mockResolvedValue([]);
  mocks.ui.jobs.mockResolvedValue([]);
});
afterEach(() => {
  useJobs().stop();
  document.body.innerHTML = "";
});

describe("App shell", () => {
  it("loads the studio data and starts job polling on mount", async () => {
    const { wrapper } = await mountApp();
    expect(mocks.ui.state).toHaveBeenCalledTimes(1);
    for (const list of [
      mocks.ui.collections.list,
      mocks.ui.seasons.list,
      mocks.ui.normProfiles.list,
      mocks.ui.procProfiles.list,
      mocks.ui.assets.list,
      mocks.ui.clips.list,
    ]) {
      expect(list).toHaveBeenCalledTimes(1);
    }
    expect(mocks.ui.jobs).toHaveBeenCalledTimes(1);
    expect(wrapper.get("main").attributes("id")).toBe("main");
    wrapper.unmount();
  });

  it("shows the current view title in the header and document title", async () => {
    const { wrapper, router } = await mountApp("/system");
    expect(wrapper.get("h1").text()).toBe("System");
    expect(document.title).toContain("System");
    await router.push("/upload");
    await flushPromises();
    expect(wrapper.get("h1").text()).toBe("Upload");
    expect(document.title).toBe("Upload · Cinema Studio");
    wrapper.unmount();
  });

  it("surfaces load errors in an alert with a working retry", async () => {
    mocks.ui.state.mockRejectedValueOnce(new Error("Studio is unreachable"));
    const { wrapper } = await mountApp();
    const alert = wrapper.get('[role="alert"]');
    expect(alert.text()).toContain("Studio is unreachable");

    await alert.get("button").trigger("click");
    await flushPromises();
    expect(mocks.ui.state).toHaveBeenCalledTimes(2);
    expect(useStudio().error.value).toBeNull();
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("keeps Library mounted while the editor sheet opens and closes", async () => {
    const { wrapper, router } = await mountApp("/");
    const library = wrapper.get('[data-test="library"]').element;
    expect(document.querySelector('[role="dialog"]')).toBeNull();

    await router.push("/clips/abc");
    await flushPromises();
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    expect(wrapper.get('[data-test="library"]').element).toBe(library);

    await router.push("/");
    await flushPromises();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(wrapper.get('[data-test="library"]').element).toBe(library);
    wrapper.unmount();
  });

  it("closing the editor sheet returns to Library", async () => {
    const { wrapper, router } = await mountApp("/clips/abc");
    const close = document.querySelector<HTMLButtonElement>('[role="dialog"] button[aria-label="Close"]')!;
    close.click();
    await flushPromises();
    expect(router.currentRoute.value.name).toBe("library");
    wrapper.unmount();
  });
});
