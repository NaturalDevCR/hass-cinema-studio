import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Job } from "@/api/types";
import { useI18n } from "@/i18n";

const store = vi.hoisted(() => ({ jobs: null as null | { value: Job[] } }));

vi.mock("@/composables/useJobs", async () => {
  const { computed, ref } = await import("vue");
  const jobs = ref<Job[]>([]);
  store.jobs = jobs;
  const active = computed(() => jobs.value.filter((j) => j.status === "queued" || j.status === "running"));
  return { useJobs: () => ({ jobs, active, start: vi.fn(), stop: vi.fn(), refresh: vi.fn() }) };
});

import JobTray from "@/components/JobTray.vue";

const job = (patch: Partial<Job> & { id: string }): Job => ({
  kind: "render",
  clip_id: "c",
  clip_title: patch.id,
  status: "done",
  progress: 1,
  error: null,
  created_at: "2026-10-03T10:00:00Z",
  started_at: null,
  finished_at: null,
  ...patch,
});

const mountTray = () => mount(JobTray, { attachTo: document.body });

beforeEach(() => {
  useI18n().setLocale("en");
  store.jobs!.value = [];
});
afterEach(() => (document.body.innerHTML = ""));

describe("JobTray", () => {
  it("shows no badge when idle and an empty message when opened", async () => {
    const wrapper = mountTray();
    expect(wrapper.find('[data-test="badge"]').exists()).toBe(false);
    const button = wrapper.get("button");
    expect(button.attributes("aria-expanded")).toBe("false");
    await button.trigger("click");
    expect(button.attributes("aria-expanded")).toBe("true");
    expect(wrapper.text()).toContain("No recent jobs");
    wrapper.unmount();
  });

  it("badges the number of active jobs", () => {
    store.jobs!.value = [
      job({ id: "a", status: "running", progress: 0.4 }),
      job({ id: "b", status: "queued", progress: 0 }),
      job({ id: "c" }),
    ];
    const wrapper = mountTray();
    expect(wrapper.get('[data-test="badge"]').text()).toBe("2");
    expect(wrapper.get("button").attributes("aria-label")).toContain("2");
    wrapper.unmount();
  });

  it("lists jobs with kind, status and accessible progress bars", async () => {
    store.jobs!.value = [
      job({ id: "bell", clip_title: "Door bell", status: "running", progress: 0.4, kind: "render" }),
      job({ id: "dog", clip_title: "Dog", status: "failed", error: "ffmpeg exited with 1", kind: "legacy_import" }),
    ];
    const wrapper = mountTray();
    await wrapper.get("button").trigger("click");
    const text = wrapper.text();
    expect(text).toContain("Door bell");
    expect(text).toContain("Render");
    expect(text).toContain("Running");
    expect(text).toContain("Legacy import");
    expect(text).toContain("ffmpeg exited with 1");

    const bars = wrapper.findAll('[role="progressbar"]');
    expect(bars).toHaveLength(1);
    expect(bars[0]!.attributes("aria-valuenow")).toBe("40");
    expect(bars[0]!.attributes("aria-valuemin")).toBe("0");
    expect(bars[0]!.attributes("aria-valuemax")).toBe("100");
    wrapper.unmount();
  });

  it("closes with Escape and returns focus to the trigger", async () => {
    const wrapper = mountTray();
    const button = wrapper.get("button");
    await button.trigger("click");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await flushPromises();
    expect(button.attributes("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(button.element);
    wrapper.unmount();
  });

  it("closes when clicking elsewhere", async () => {
    const wrapper = mountTray();
    await wrapper.get("button").trigger("click");
    document.body.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    await flushPromises();
    expect(wrapper.get("button").attributes("aria-expanded")).toBe("false");
    wrapper.unmount();
  });
});
