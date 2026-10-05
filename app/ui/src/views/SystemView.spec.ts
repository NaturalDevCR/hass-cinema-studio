import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useI18n } from "@/i18n";
import { makeState } from "@/test/system";

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

import SystemView from "@/views/SystemView.vue";
import { useStudio } from "@/composables/useStudio";

beforeEach(() => {
  useI18n().setLocale("en");
  vi.clearAllMocks();
  mocks.ui.collections.list.mockResolvedValue([]);
  mocks.ui.seasons.list.mockResolvedValue([]);
  mocks.ui.normProfiles.list.mockResolvedValue([]);
  mocks.ui.procProfiles.list.mockResolvedValue([]);
  mocks.ui.assets.list.mockResolvedValue([]);
  mocks.ui.clips.list.mockResolvedValue([]);
  mocks.ui.jobs.mockResolvedValue([]);
});
afterEach(() => {
  document.body.innerHTML = "";
});

describe("SystemView", () => {
  it("refetches state when it opens, so storage figures loaded earlier are not stale", async () => {
    const stale = makeState();
    stale.storage = { ...stale.storage, renders_bytes: 0 };
    mocks.ui.state.mockResolvedValue(stale);
    await useStudio().refresh();
    expect(mocks.ui.state).toHaveBeenCalledTimes(1);

    const fresh = makeState();
    fresh.storage = { ...fresh.storage, renders_bytes: 3 * 1024 * 1024 };
    mocks.ui.state.mockResolvedValue(fresh);
    const wrapper = mount(SystemView, { attachTo: document.body });
    await flushPromises();
    expect(mocks.ui.state).toHaveBeenCalledTimes(2);
    expect(useStudio().state.value?.storage.renders_bytes).toBe(3 * 1024 * 1024);
    wrapper.unmount();
  });
});
