import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Asset, Clip, Collection, NormalizationProfile, ProcessingProfile, Season, State } from "@/api/types";

const mocks = vi.hoisted(() => ({
  ui: {
    state: vi.fn(),
    collections: { list: vi.fn() },
    seasons: { list: vi.fn() },
    normProfiles: { list: vi.fn() },
    procProfiles: { list: vi.fn() },
    assets: { list: vi.fn() },
    clips: { list: vi.fn() },
  },
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ui: mocks.ui,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const collection = { id: "regular", name: "Regular" } as Collection;
const season = { id: "regular", name: "Regular" } as Season;
const normProfile = { id: "standard", name: "Standard" } as NormalizationProfile;
const procProfile = { id: "compatibility-4k-loudness", name: "Compatibility 4K" } as ProcessingProfile;
const asset = { filename: "intro.mp4", size: 10, sha256: "x", status: "ready" } as Asset;
const clip = { id: "c1", title: "Trailer" } as Clip;
const state = { version: "1.0.0" } as State;

async function load() {
  vi.resetModules();
  const { ApiError } = await import("@/api/client");
  const { useStudio } = await import("@/composables/useStudio");
  return { ApiError, useStudio };
}

beforeEach(() => {
  vi.resetAllMocks(); // also drops queued mock*Once values a failing test left behind
  mocks.ui.state.mockResolvedValue(state);
  mocks.ui.collections.list.mockResolvedValue([collection]);
  mocks.ui.seasons.list.mockResolvedValue([season]);
  mocks.ui.normProfiles.list.mockResolvedValue([normProfile]);
  mocks.ui.procProfiles.list.mockResolvedValue([procProfile]);
  mocks.ui.assets.list.mockResolvedValue([asset]);
  mocks.ui.clips.list.mockResolvedValue([clip]);
});

describe("useStudio", () => {
  it("starts out loading and not loaded so views can skip their empty state", async () => {
    const { useStudio } = await load();
    const studio = useStudio();
    expect(studio.loading.value).toBe(true);
    expect(studio.loaded.value).toBe(false);
    await studio.refresh();
    expect(studio.loading.value).toBe(false);
    expect(studio.loaded.value).toBe(true);
  });

  it("settles loading but stays not loaded when the first refresh fails; later success loads", async () => {
    const { useStudio } = await load();
    mocks.ui.state.mockRejectedValueOnce(new Error("offline"));
    const studio = useStudio();
    await studio.refresh();
    expect(studio.loading.value).toBe(false);
    expect(studio.loaded.value).toBe(false);
    await studio.refresh();
    expect(studio.loaded.value).toBe(true);
  });

  it("keeps loaded true (and the old data) when a later refresh fails", async () => {
    const { useStudio } = await load();
    const studio = useStudio();
    await studio.refresh();
    mocks.ui.clips.list.mockRejectedValueOnce(new Error("blip"));
    await studio.refresh();
    expect(studio.loaded.value).toBe(true);
    expect(studio.clips.value).toEqual([clip]);
    expect(studio.error.value).toBe("blip");
  });

  it("loads everything in parallel", async () => {
    const { useStudio } = await load();
    const gates = Object.fromEntries(
      ["state", "collections", "seasons", "normProfiles", "procProfiles", "assets", "clips"].map((k) => [
        k,
        deferred<unknown>(),
      ]),
    );
    mocks.ui.state.mockReturnValue(gates.state.promise);
    mocks.ui.collections.list.mockReturnValue(gates.collections.promise);
    mocks.ui.seasons.list.mockReturnValue(gates.seasons.promise);
    mocks.ui.normProfiles.list.mockReturnValue(gates.normProfiles.promise);
    mocks.ui.procProfiles.list.mockReturnValue(gates.procProfiles.promise);
    mocks.ui.assets.list.mockReturnValue(gates.assets.promise);
    mocks.ui.clips.list.mockReturnValue(gates.clips.promise);

    const studio = useStudio();
    const pending = studio.refresh();
    expect(studio.loading.value).toBe(true);
    // every request is in flight before any of them resolved
    expect(mocks.ui.state).toHaveBeenCalledTimes(1);
    expect(mocks.ui.collections.list).toHaveBeenCalledTimes(1);
    expect(mocks.ui.seasons.list).toHaveBeenCalledTimes(1);
    expect(mocks.ui.normProfiles.list).toHaveBeenCalledTimes(1);
    expect(mocks.ui.procProfiles.list).toHaveBeenCalledTimes(1);
    expect(mocks.ui.assets.list).toHaveBeenCalledTimes(1);
    expect(mocks.ui.clips.list).toHaveBeenCalledTimes(1);

    gates.state.resolve(state);
    gates.collections.resolve([collection]);
    gates.seasons.resolve([season]);
    gates.normProfiles.resolve([normProfile]);
    gates.procProfiles.resolve([procProfile]);
    gates.assets.resolve([asset]);
    gates.clips.resolve([clip]);
    await pending;

    expect(studio.loading.value).toBe(false);
    expect(studio.error.value).toBeNull();
    expect(studio.state.value).toEqual(state);
    expect(studio.collections.value).toEqual([collection]);
    expect(studio.seasons.value).toEqual([season]);
    expect(studio.normProfiles.value).toEqual([normProfile]);
    expect(studio.procProfiles.value).toEqual([procProfile]);
    expect(studio.assets.value).toEqual([asset]);
    expect(studio.clips.value).toEqual([clip]);
  });

  it("shares one store between callers", async () => {
    const { useStudio } = await load();
    await useStudio().refresh();
    expect(useStudio().clips.value).toEqual([clip]);
  });

  it("deduplicates overlapping refreshes", async () => {
    const { useStudio } = await load();
    const studio = useStudio();
    await Promise.all([studio.refresh(), studio.refresh()]);
    expect(mocks.ui.state).toHaveBeenCalledTimes(1);
  });

  it.each([false, true])("forced refresh waits for an in-flight refresh then fetches again (first fails: %s)", async (fails) => {
    const { useStudio } = await load();
    const studio = useStudio();
    const first = deferred<State>();
    const second = deferred<State>();
    mocks.ui.state.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const a = studio.refresh();
    const b = studio.refresh({ force: true });
    const c = studio.refresh({ force: true });
    expect(mocks.ui.state).toHaveBeenCalledTimes(1);
    let settled = false;
    void b.then(() => (settled = true));
    if (fails) first.reject(new Error("offline"));
    else first.resolve(state);
    await a;
    await Promise.resolve();
    expect(mocks.ui.state).toHaveBeenCalledTimes(2);
    expect(settled).toBe(false);
    const fresh = { ...state, version: "2.0.0" };
    second.resolve(fresh);
    await Promise.all([b, c]);
    expect(studio.state.value).toEqual(fresh);
    expect(studio.error.value).toBeNull();
    expect(studio.loading.value).toBe(false);
    await studio.refresh({ force: true });
    expect(mocks.ui.state).toHaveBeenCalledTimes(3);
  });

  it("records the error message instead of throwing, then recovers", async () => {
    const { useStudio, ApiError } = await load();
    mocks.ui.clips.list.mockRejectedValueOnce(new ApiError(500, "Database is locked"));
    const studio = useStudio();
    await expect(studio.refresh()).resolves.toBeUndefined();
    expect(studio.error.value).toBe("Database is locked");
    expect(studio.loading.value).toBe(false);

    await studio.refresh();
    expect(studio.error.value).toBeNull();
    expect(studio.clips.value).toEqual([clip]);
  });

  it("refreshClips only reloads the clip list", async () => {
    const { useStudio } = await load();
    const studio = useStudio();
    mocks.ui.clips.list.mockResolvedValueOnce([clip, { id: "c2" } as Clip]);
    await studio.refreshClips();
    expect(studio.clips.value).toHaveLength(2);
    expect(mocks.ui.state).not.toHaveBeenCalled();
    expect(mocks.ui.collections.list).not.toHaveBeenCalled();
  });

  it("clears a previous error when refreshClips succeeds once the studio has loaded", async () => {
    const { useStudio } = await load();
    const studio = useStudio();
    await studio.refresh();
    mocks.ui.clips.list.mockRejectedValueOnce(new Error("offline"));
    await studio.refreshClips();
    expect(studio.error.value).toBe("offline");
    await studio.refreshClips();
    expect(studio.error.value).toBeNull();
  });

  it("keeps the error of a failed first load when a lightweight refreshClips succeeds", async () => {
    const { useStudio } = await load();
    const studio = useStudio();
    mocks.ui.state.mockRejectedValueOnce(new Error("Studio is unreachable"));
    await studio.refresh();
    expect(studio.loaded.value).toBe(false);
    expect(studio.error.value).toBe("Studio is unreachable");

    // e.g. a job-completion poll succeeds while the collections/state are still missing
    await studio.refreshClips();
    expect(studio.clips.value).toEqual([clip]);
    expect(studio.error.value).toBe("Studio is unreachable");
    expect(studio.loaded.value).toBe(false);

    await studio.refresh(); // Retry
    expect(studio.error.value).toBeNull();
    expect(studio.loaded.value).toBe(true);
  });

  it("makes a refreshClips call that arrives mid-flight wait, then fetch once more", async () => {
    const { useStudio } = await load();
    const studio = useStudio();
    await studio.refresh();
    mocks.ui.clips.list.mockClear();
    const first = deferred<Clip[]>();
    const second = deferred<Clip[]>();
    mocks.ui.clips.list.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    const a = studio.refreshClips();
    const b = studio.refreshClips();
    expect(mocks.ui.clips.list).toHaveBeenCalledTimes(1);
    let bSettled = false;
    void b.then(() => (bSettled = true));

    // the request that was already in flight may predate the caller's mutation: it must not satisfy b
    first.resolve([clip]);
    await a;
    await Promise.resolve();
    expect(mocks.ui.clips.list).toHaveBeenCalledTimes(2);
    expect(bSettled).toBe(false);

    second.resolve([clip, { id: "c2" } as Clip]);
    await b;
    expect(studio.clips.value).toHaveLength(2);
  });

  it("coalesces many concurrent refreshClips callers into one trailing request", async () => {
    const { useStudio } = await load();
    const studio = useStudio();
    await studio.refresh();
    mocks.ui.clips.list.mockClear();
    const first = deferred<Clip[]>();
    mocks.ui.clips.list.mockReturnValueOnce(first.promise);

    const calls = [studio.refreshClips(), studio.refreshClips(), studio.refreshClips(), studio.refreshClips()];
    expect(mocks.ui.clips.list).toHaveBeenCalledTimes(1);
    first.resolve([clip]);
    await Promise.all(calls);
    expect(mocks.ui.clips.list).toHaveBeenCalledTimes(2);

    // everything settled: the next call starts a fresh request
    await studio.refreshClips();
    expect(mocks.ui.clips.list).toHaveBeenCalledTimes(3);
  });

  it("still settles every caller (and keeps the error) when the trailing refreshClips fails", async () => {
    const { useStudio } = await load();
    const studio = useStudio();
    await studio.refresh();
    const first = deferred<Clip[]>();
    mocks.ui.clips.list.mockReturnValueOnce(first.promise).mockRejectedValueOnce(new Error("blip"));
    const a = studio.refreshClips();
    const b = studio.refreshClips();
    first.resolve([clip]);
    await expect(Promise.all([a, b])).resolves.toBeDefined();
    expect(studio.error.value).toBe("blip");
  });

  it("reports refreshClips failures through error", async () => {
    const { useStudio } = await load();
    mocks.ui.clips.list.mockRejectedValueOnce(new Error("offline"));
    const studio = useStudio();
    await studio.refreshClips();
    expect(studio.error.value).toBe("offline");
  });

  it("looks entities up by id", async () => {
    const { useStudio } = await load();
    const studio = useStudio();
    await studio.refresh();
    expect(studio.collectionById("regular")).toEqual(collection);
    expect(studio.seasonById("regular")).toEqual(season);
    expect(studio.normProfileById("standard")).toEqual(normProfile);
    expect(studio.procProfileById("compatibility-4k-loudness")).toEqual(procProfile);
    expect(studio.collectionById("nope")).toBeUndefined();
    expect(studio.normProfileById(null)).toBeUndefined();
    expect(studio.procProfileById(undefined)).toBeUndefined();
  });
});
