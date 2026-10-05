import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Job } from "@/api/types";

const mocks = vi.hoisted(() => ({
  ui: { jobs: vi.fn() },
  refreshClips: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ui: mocks.ui,
}));
vi.mock("@/composables/useStudio", () => ({
  useStudio: () => ({ refreshClips: mocks.refreshClips }),
}));

const job = (patch: Partial<Job> & { id: string }): Job => ({
  kind: "render",
  clip_id: "c1",
  clip_title: "Doorbell",
  status: "done",
  progress: 1,
  error: null,
  created_at: "2026-10-03T10:00:00Z",
  started_at: "2026-10-03T10:00:01Z",
  finished_at: "2026-10-03T10:00:02Z",
  ...patch,
});

async function load() {
  vi.resetModules();
  const { useJobs } = await import("@/composables/useJobs");
  const { useToast } = await import("@/composables/useToast");
  return { jobs: useJobs(), toast: useToast() };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  mocks.refreshClips.mockResolvedValue(undefined);
});
afterEach(() => vi.useRealTimers());

describe("useJobs polling", () => {
  it("fetches immediately and then every 10 s while idle", async () => {
    mocks.ui.jobs.mockResolvedValue([job({ id: "old" })]);
    const { jobs } = await load();
    jobs.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.ui.jobs).toHaveBeenCalledTimes(1);
    expect(jobs.jobs.value).toHaveLength(1);
    expect(jobs.active.value).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(9_999);
    expect(mocks.ui.jobs).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(mocks.ui.jobs).toHaveBeenCalledTimes(2);
    jobs.stop();
  });

  it("polls every 1500 ms while a job is queued or running", async () => {
    mocks.ui.jobs.mockResolvedValue([
      job({ id: "a", status: "running", progress: 0.4 }),
      job({ id: "b", status: "queued", progress: 0 }),
      job({ id: "c" }),
    ]);
    const { jobs } = await load();
    jobs.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(jobs.active.value.map((j) => j.id)).toEqual(["a", "b"]);

    await vi.advanceTimersByTimeAsync(1_500);
    expect(mocks.ui.jobs).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(3_000);
    expect(mocks.ui.jobs).toHaveBeenCalledTimes(4);
    jobs.stop();
  });

  it("refreshes clips and toasts once when a job finishes", async () => {
    mocks.ui.jobs
      .mockResolvedValueOnce([job({ id: "a", status: "running", progress: 0.5 })])
      .mockResolvedValue([job({ id: "a", status: "done" })]);
    const { jobs, toast } = await load();
    jobs.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.refreshClips).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1_500);
    expect(mocks.refreshClips).toHaveBeenCalledTimes(1);
    expect(toast.toasts.value.some((t) => t.kind === "success" && t.message.includes("Doorbell"))).toBe(true);

    await vi.advanceTimersByTimeAsync(10_000);
    expect(mocks.refreshClips).toHaveBeenCalledTimes(1);
    jobs.stop();
  });

  it("does not replay history: jobs already finished at first load stay quiet", async () => {
    mocks.ui.jobs.mockResolvedValue([job({ id: "old1" }), job({ id: "old2", status: "failed", error: "x" })]);
    const { jobs, toast } = await load();
    jobs.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(mocks.refreshClips).not.toHaveBeenCalled();
    expect(toast.toasts.value).toHaveLength(0);
    jobs.stop();
  });

  it("catches jobs that start and finish between two polls", async () => {
    mocks.ui.jobs
      .mockResolvedValueOnce([])
      .mockResolvedValue([job({ id: "fast", kind: "render", status: "done" })]);
    const { jobs } = await load();
    jobs.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(mocks.refreshClips).toHaveBeenCalledTimes(1);
    jobs.stop();
  });

  it("surfaces failures as an error toast carrying the job error", async () => {
    mocks.ui.jobs
      .mockResolvedValueOnce([job({ id: "a", status: "running", progress: 0.1 })])
      .mockResolvedValue([job({ id: "a", status: "failed", error: "ffmpeg exited with 1" })]);
    const { jobs, toast } = await load();
    jobs.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1_500);
    const error = toast.toasts.value.find((t) => t.kind === "error");
    expect(error?.message).toContain("ffmpeg exited with 1");
    jobs.stop();
  });

  it("keeps the last list when a poll fails and keeps polling", async () => {
    mocks.ui.jobs
      .mockResolvedValueOnce([job({ id: "a", status: "running", progress: 0.2 })])
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue([job({ id: "a", status: "running", progress: 0.9 })]);
    const { jobs } = await load();
    jobs.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1_500);
    expect(jobs.jobs.value[0]?.progress).toBe(0.2);
    expect(jobs.error.value).toBe("offline");
    await vi.advanceTimersByTimeAsync(1_500);
    expect(jobs.jobs.value[0]?.progress).toBe(0.9);
    expect(jobs.error.value).toBeNull();
    jobs.stop();
  });

  it("collapses more than three finished jobs into one summary toast", async () => {
    const many = (status: "done" | "failed", n: number, from = 0) =>
      Array.from({ length: n }, (_, i) => job({ id: `j${from + i}`, status, error: status === "failed" ? "x" : null }));
    mocks.ui.jobs
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([...many("done", 4)])
      .mockResolvedValue([...many("done", 4), ...many("done", 3, 10), ...many("failed", 2, 20)]);
    const { jobs, toast } = await load();
    jobs.start();
    await vi.advanceTimersByTimeAsync(0);

    await vi.advanceTimersByTimeAsync(10_000);
    expect(toast.toasts.value).toHaveLength(1);
    expect(toast.toasts.value[0]).toMatchObject({ kind: "success", message: "4 jobs finished" });
    expect(mocks.refreshClips).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(10_000);
    // 5 more finished at once, 2 of them failed: still one toast (the earlier one timed out), now an error
    expect(toast.toasts.value).toHaveLength(1);
    expect(toast.toasts.value[0]).toMatchObject({ kind: "error", message: "5 jobs finished, 2 failed" });
    expect(mocks.refreshClips).toHaveBeenCalledTimes(2);
    jobs.stop();
  });

  it("still toasts individually up to three finished jobs", async () => {
    mocks.ui.jobs
      .mockResolvedValueOnce([])
      .mockResolvedValue([
        job({ id: "a", clip_title: "A" }),
        job({ id: "b", clip_title: "B" }),
        job({ id: "c", clip_title: "C" }),
      ]);
    const { jobs, toast } = await load();
    jobs.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(toast.toasts.value.map((t) => t.message)).toEqual(["Rendered “A”", "Rendered “B”", "Rendered “C”"]);
    jobs.stop();
  });

  it("start() is idempotent and stop() halts polling", async () => {
    mocks.ui.jobs.mockResolvedValue([]);
    const { jobs } = await load();
    jobs.start();
    jobs.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.ui.jobs).toHaveBeenCalledTimes(1);
    jobs.stop();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(mocks.ui.jobs).toHaveBeenCalledTimes(1);
  });

  it("refresh() waits for a stale in-flight poll and then makes a fresh request", async () => {
    let release!: (list: Job[]) => void;
    mocks.ui.jobs
      .mockImplementationOnce(() => new Promise<Job[]>((resolve) => (release = resolve)))
      .mockResolvedValue([job({ id: "queued-after", status: "queued", progress: 0 })]);
    const { jobs } = await load();
    jobs.start(); // poll #1 is now in flight, sent before the caller queues anything
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.ui.jobs).toHaveBeenCalledTimes(1);

    const refreshed = jobs.refresh(); // caller queued work, wants to see it
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.ui.jobs).toHaveBeenCalledTimes(1); // not reused, not duplicated yet

    release([]);
    await refreshed;
    expect(mocks.ui.jobs).toHaveBeenCalledTimes(2);
    expect(jobs.active.value.map((j) => j.id)).toEqual(["queued-after"]);
    jobs.stop();
  });

  it("refresh() polls right away so callers need not wait for the timer", async () => {
    mocks.ui.jobs.mockResolvedValue([]);
    const { jobs } = await load();
    jobs.start();
    await vi.advanceTimersByTimeAsync(0);
    await jobs.refresh();
    expect(mocks.ui.jobs).toHaveBeenCalledTimes(2);
    jobs.stop();
  });
});

describe("job kinds", () => {
  const finishWith = async (finished: Job) => {
    mocks.ui.jobs.mockResolvedValueOnce([]).mockResolvedValue([finished]);
    const { jobs, toast } = await load();
    jobs.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(10_000);
    jobs.stop();
    return toast.toasts.value.map((t) => ({ kind: t.kind, message: t.message }));
  };

  it.each(["probe", "thumbs", "legacy_import"] as const)("finishes %s jobs quietly but refreshes clips", async (kind) => {
    expect(await finishWith(job({ id: "q", kind }))).toEqual([]);
    expect(mocks.refreshClips).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["probe", "Couldn't analyze"],
    ["render", "Couldn't render “Doorbell”"],
    ["preview", "Couldn't render a preview"],
    ["thumbs", "Couldn't create thumbnails"],
    ["legacy_import", "Couldn't import"],
  ] as const)("names the failed %s job", async (kind, text) => {
    const toasts = await finishWith(job({ id: "f", kind, status: "failed", error: "boom" }));
    expect(toasts).toHaveLength(1);
    expect(toasts[0]?.kind).toBe("error");
    expect(toasts[0]?.message).toContain(text);
    expect(toasts[0]?.message).toContain("boom");
  });

  it("falls back to an unknown error when the job carries none", async () => {
    const toasts = await finishWith(job({ id: "f", kind: "render", status: "failed", error: null }));
    expect(toasts[0]?.message).toContain("Unknown error");
  });
});

it("leaves editor preview failures inline without duplicate or summary toasts", async () => {
  const { jobs, toast } = await load();
  mocks.ui.jobs.mockResolvedValueOnce([]);
  await jobs.refresh();
  const release = jobs.suppressPreviewToast("c1");
  mocks.ui.jobs.mockResolvedValue([job({ id: "preview-inline", kind: "preview", status: "failed", error: "bad render" })]);
  await jobs.refresh();
  expect(toast.toasts.value).toHaveLength(0);
  expect(mocks.refreshClips).toHaveBeenCalledOnce();
  release();
  mocks.ui.jobs.mockResolvedValue([job({ id: "preview-external", kind: "preview", status: "failed", error: "external failure" })]);
  await jobs.refresh();
  expect(toast.toasts.value[0]?.message).toContain("external failure");
});
