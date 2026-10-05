import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import type { Job } from "@/api/types";
import JobsPanel from "./JobsPanel.vue";

const jobs = ref<Job[]>([]);
vi.mock("@/composables/useJobs", () => ({ useJobs: () => ({ jobs, error: ref(null), refresh: vi.fn() }) }));

const job = (n: number): Job =>
  ({ id: `j${n}`, kind: "render", status: "done", progress: 1, error: null, clip_id: `c${n}`, clip_title: `Clip ${n}`,
    created_at: new Date(Date.UTC(2026, 0, 1, 0, n)).toISOString() }) as Job;

describe("JobsPanel", () => {
  it("caps the list at the 30 most recent jobs, newest first", () => {
    jobs.value = Array.from({ length: 45 }, (_, i) => job(i)).reverse().sort((a, b) => (a.id < b.id ? -1 : 1));
    const wrapper = mount(JobsPanel);
    const titles = wrapper.findAll("li .font-medium").map((el) => el.text());
    expect(titles).toHaveLength(30);
    expect(titles[0]).toBe("Clip 44");
    expect(titles[29]).toBe("Clip 15");
  });
});
