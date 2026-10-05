import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProcessingProfileSettings, Recipe, Settings } from "@/api/types";
import { ApiError, api, filmstripUrl, mediaUrl, messageOf, posterUrl, ui } from "@/api/client";
import { useI18n } from "@/i18n";

const fetchMock = vi.fn();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function lastCall() {
  const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
  return { url, init, headers: new Headers(init.headers) };
}

beforeEach(() => {
  useI18n().setLocale("en");
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("api()", () => {
  it("keeps the path relative (Ingress safe) and parses JSON", async () => {
    fetchMock.mockResolvedValue(jsonResponse([{ id: "x" }]));
    const out = await api<{ id: string }[]>("api/ui/clips");
    expect(out).toEqual([{ id: "x" }]);
    expect(lastCall().url).toBe("api/ui/clips");
    expect(lastCall().headers.get("accept")).toContain("application/json");
  });

  it("strips accidental leading slashes", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    await api("/api/ui/state");
    expect(lastCall().url).toBe("api/ui/state");
  });

  it("serializes `json` with a content-type header", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await api("api/ui/collections", { method: "POST", json: { name: "Doors" } });
    const { init, headers } = lastCall();
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ name: "Doors" }));
    expect(headers.get("content-type")).toBe("application/json");
  });

  it("does not force a content-type on raw bodies", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ received: 3 }));
    const blob = new Blob(["abc"]);
    await api("api/ui/uploads/u/chunks/0", { method: "PUT", body: blob });
    expect(lastCall().init.body).toBe(blob);
    expect(lastCall().headers.get("content-type")).toBeNull();
  });

  it("turns {detail} errors into ApiError", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Collection already exists" }, 409));
    const failure = api("api/ui/collections", { method: "POST", json: {} });
    await expect(failure).rejects.toBeInstanceOf(ApiError);
    await expect(failure).rejects.toMatchObject({
      status: 409,
      detail: "Collection already exists",
      message: "Collection already exists",
    });
  });

  it("flattens FastAPI validation arrays", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: [{ loc: ["body", "name"], msg: "Field required", type: "missing" }] }, 422),
    );
    await expect(api("api/ui/collections")).rejects.toMatchObject({ status: 422, detail: "name: Field required" });
  });

  it("names the offending field using the last loc element", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          detail: [
            { loc: ["body", "title"], msg: "Field required", type: "missing" },
            { loc: ["body", "tags", 0], msg: "Input should be a valid string", type: "string_type" },
            { loc: ["body"], msg: "Bad body", type: "x" },
          ],
        },
        422,
      ),
    );
    await expect(api("api/ui/clips/s1", { method: "PATCH", json: {} })).rejects.toMatchObject({
      status: 422,
      detail: "title: Field required; tags: Input should be a valid string; Bad body",
    });
  });

  it("turns a 2xx response that is not JSON into an ApiError, not a SyntaxError", async () => {
    fetchMock.mockResolvedValue(new Response("<html>Ingress login</html>", { status: 200 }));
    const error = await api("api/ui/state").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 200, detail: "Invalid server response" });
  });

  it("treats an empty 2xx body as undefined", async () => {
    fetchMock.mockResolvedValue(new Response("", { status: 200 }));
    await expect(api("api/ui/token/rotate", { method: "POST" })).resolves.toBeUndefined();
  });

  it("falls back to a readable message for non-JSON failures", async () => {
    fetchMock.mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 }));
    const error = await api("api/ui/state").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(502);
    expect((error as ApiError).detail).toContain("502");
  });

  it("maps network failures to ApiError status 0", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api("api/ui/state")).rejects.toMatchObject({ status: 0 });
  });

  it("lets aborts through untouched", async () => {
    const abort = new DOMException("aborted", "AbortError");
    fetchMock.mockRejectedValue(abort);
    await expect(api("api/ui/state")).rejects.toBe(abort);
  });

  it("returns undefined for 204", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api("api/ui/collections/x", { method: "DELETE" })).resolves.toBeUndefined();
  });
});

describe("media URLs", () => {
  it("builds relative stream URLs with an optional cache buster", () => {
    expect(mediaUrl("abc", "original")).toBe("api/ui/clips/abc/original");
    expect(mediaUrl("abc", "render", 3)).toBe("api/ui/clips/abc/render?v=3");
    expect(mediaUrl("abc", "preview", "t1")).toBe("api/ui/clips/abc/preview?v=t1");
    expect(mediaUrl("abc", "render", "")).toBe("api/ui/clips/abc/render");
  });

  it("builds poster and filmstrip URLs", () => {
    expect(posterUrl("abc")).toBe("api/ui/clips/abc/poster.jpg");
    expect(posterUrl("abc", 4)).toBe("api/ui/clips/abc/poster.jpg?v=4");
    expect(filmstripUrl("abc", 7)).toBe("api/ui/clips/abc/filmstrip/7.jpg");
    expect(filmstripUrl("abc", 0, "x y")).toBe("api/ui/clips/abc/filmstrip/0.jpg?v=x%20y");
  });
});

describe("ui endpoints", () => {
  beforeEach(() => fetchMock.mockImplementation(async () => jsonResponse({})));

  const call = async (run: () => Promise<unknown>) => {
    await run();
    const { url, init, headers } = lastCall();
    return {
      url,
      method: init.method ?? "GET",
      body: typeof init.body === "string" ? JSON.parse(init.body) : init.body,
      contentType: headers.get("content-type"),
    };
  };

  const recipe: Recipe = {
    trim_start: 0,
    trim_end: null,
    crop: null,
    fade_in: null,
    fade_out: null,
    gain_db: 0,
    profile_id: null,
    lead_in: 2,
    tail_out: 2,
  };

  it("covers state, token and settings", async () => {
    expect(await call(() => ui.state())).toMatchObject({ url: "api/ui/state", method: "GET" });
    expect(await call(() => ui.token())).toMatchObject({ url: "api/ui/token", method: "GET" });
    expect(await call(() => ui.rotateToken())).toMatchObject({ url: "api/ui/token/rotate", method: "POST" });
    expect(await call(() => ui.settings.get())).toMatchObject({ url: "api/ui/settings", method: "GET" });
    const settings: Settings = {
      max_upload_mb: 50,
      max_duration_s: 60,
      default_lead_in: 2,
      default_tail_out: 2,
      disk_reserve_bytes: 1_000_000,
      test_targets: [],
      protected_entities: ["media_player.otocuma_dp"],
    };
    expect(await call(() => ui.settings.put(settings))).toMatchObject({
      url: "api/ui/settings",
      method: "PUT",
      body: settings,
    });
  });

  it("covers collections", async () => {
    expect(await call(() => ui.collections.list())).toMatchObject({ url: "api/ui/collections", method: "GET" });
    expect(await call(() => ui.collections.create({ name: "Trailers", playback_mode: "custom" }))).toMatchObject({
      url: "api/ui/collections",
      method: "POST",
      body: { name: "Trailers", playback_mode: "custom" },
    });
    expect(await call(() => ui.collections.update("trailers", { color: "#fff" }))).toMatchObject({
      url: "api/ui/collections/trailers",
      method: "PATCH",
      body: { color: "#fff" },
    });
    expect(await call(() => ui.collections.remove("trailers"))).toMatchObject({
      url: "api/ui/collections/trailers",
      method: "DELETE",
    });
    expect(await call(() => ui.collections.order("trailers", ["b", "a"]))).toMatchObject({
      url: "api/ui/collections/trailers/order",
      method: "PUT",
      body: { clip_ids: ["b", "a"] },
    });
  });

  it("covers seasons", async () => {
    expect(await call(() => ui.seasons.list())).toMatchObject({ url: "api/ui/seasons", method: "GET" });
    expect(
      await call(() =>
        ui.seasons.create({ name: "Halloween", start: "10-01", end: "10-31", collection_id: "horror" }),
      ),
    ).toMatchObject({ method: "POST", url: "api/ui/seasons", body: { collection_id: "horror" } });
    expect(await call(() => ui.seasons.update("halloween", { priority: 5 }))).toMatchObject({
      url: "api/ui/seasons/halloween",
      method: "PATCH",
      body: { priority: 5 },
    });
    expect(await call(() => ui.seasons.remove("halloween"))).toMatchObject({
      url: "api/ui/seasons/halloween",
      method: "DELETE",
    });
    expect(await call(() => ui.seasons.resolve("2026-10-31"))).toMatchObject({
      url: "api/ui/seasons/resolve?date=2026-10-31",
      method: "GET",
    });
  });

  it("covers normalization profiles", async () => {
    expect(await call(() => ui.normProfiles.list())).toMatchObject({
      url: "api/ui/normalization-profiles",
      method: "GET",
    });
    expect(
      await call(() => ui.normProfiles.create({ name: "Mine", target_lufs: -16, true_peak: -1.5, lra: 11 })),
    ).toMatchObject({ url: "api/ui/normalization-profiles", method: "POST" });
    expect(await call(() => ui.normProfiles.update("loud", { target_lufs: -12 }))).toMatchObject({
      url: "api/ui/normalization-profiles/loud",
      method: "PATCH",
      body: { target_lufs: -12 },
    });
    expect(await call(() => ui.normProfiles.remove("loud"))).toMatchObject({
      url: "api/ui/normalization-profiles/loud",
      method: "DELETE",
    });
    expect(await call(() => ui.normProfiles.apply("loud", { collection_id: "regular" }))).toMatchObject({
      url: "api/ui/normalization-profiles/loud/apply",
      method: "POST",
      body: { collection_id: "regular" },
    });
    expect(await call(() => ui.normProfiles.apply("loud", { clip_ids: ["a"] }))).toMatchObject({
      body: { clip_ids: ["a"] },
    });
  });

  it("covers processing profiles", async () => {
    const settings = { profile_version: 1 } as ProcessingProfileSettings;
    expect(await call(() => ui.procProfiles.list())).toMatchObject({
      url: "api/ui/processing-profiles",
      method: "GET",
    });
    expect(await call(() => ui.procProfiles.create({ name: "4K", settings }))).toMatchObject({
      url: "api/ui/processing-profiles",
      method: "POST",
      body: { name: "4K", settings },
    });
    expect(await call(() => ui.procProfiles.update("p1", { name: "Renamed" }))).toMatchObject({
      url: "api/ui/processing-profiles/p1",
      method: "PATCH",
      body: { name: "Renamed" },
    });
    expect(await call(() => ui.procProfiles.remove("p1"))).toMatchObject({
      url: "api/ui/processing-profiles/p1",
      method: "DELETE",
    });
  });

  it("covers assets, uploading the file as multipart form data", async () => {
    expect(await call(() => ui.assets.list())).toMatchObject({ url: "api/ui/assets", method: "GET" });
    const file = new File(["x"], "intro.mp4", { type: "video/mp4" });
    const upload = await call(() => ui.assets.upload(file));
    expect(upload).toMatchObject({ url: "api/ui/assets", method: "POST" });
    expect(upload.body).toBeInstanceOf(FormData);
    expect((upload.body as FormData).get("file")).toBeInstanceOf(File);
    expect(((upload.body as FormData).get("file") as File).name).toBe("intro.mp4");
    expect(upload.contentType).toBeNull();
    expect(await call(() => ui.assets.remove("intro 1.mp4"))).toMatchObject({
      url: "api/ui/assets/intro%201.mp4",
      method: "DELETE",
    });
  });

  it("covers clips", async () => {
    expect(await call(() => ui.clips.list())).toMatchObject({ url: "api/ui/clips", method: "GET" });
    expect(await call(() => ui.clips.get("c1"))).toMatchObject({ url: "api/ui/clips/c1", method: "GET" });
    expect(await call(() => ui.clips.update("c1", { title: "New" }))).toMatchObject({
      url: "api/ui/clips/c1",
      method: "PATCH",
      body: { title: "New" },
    });
    expect(await call(() => ui.clips.putRecipe("c1", recipe))).toMatchObject({
      url: "api/ui/clips/c1/recipe",
      method: "PUT",
      body: recipe,
    });
    expect(await call(() => ui.clips.preview("c1", recipe))).toMatchObject({
      url: "api/ui/clips/c1/preview",
      method: "POST",
      body: recipe,
    });
    expect(await call(() => ui.clips.rerender("c1"))).toMatchObject({
      url: "api/ui/clips/c1/rerender",
      method: "POST",
    });
    expect(await call(() => ui.clips.remove("c1"))).toMatchObject({ url: "api/ui/clips/c1", method: "DELETE" });
    expect(await call(() => ui.clips.bulk({ ids: ["c1"], set: { enabled: false } }))).toMatchObject({
      url: "api/ui/clips/bulk",
      method: "POST",
      body: { ids: ["c1"], set: { enabled: false } },
    });
    expect(await call(() => ui.clips.test("c1", { target_id: "t", source: "preview" }))).toMatchObject({
      url: "api/ui/clips/c1/test",
      method: "POST",
      body: { target_id: "t", source: "preview" },
    });
    expect(await call(() => ui.clips.replaceSource("c1", "u9"))).toMatchObject({
      url: "api/ui/clips/c1/source",
      method: "POST",
      body: { upload_id: "u9" },
    });
  });

  it("covers chunked uploads", async () => {
    expect(await call(() => ui.uploads.create("a.mp4", 12))).toMatchObject({
      url: "api/ui/uploads",
      method: "POST",
      body: { filename: "a.mp4", size: 12 },
    });
    const blob = new Blob(["xyz"]);
    const chunk = await call(() => ui.uploads.chunk("u1", 2, blob));
    expect(chunk).toMatchObject({ url: "api/ui/uploads/u1/chunks/2", method: "PUT", body: blob });
    expect(chunk.contentType).toBe("application/octet-stream");
    const done = { collection_id: "regular", title: "Trailer" };
    expect(await call(() => ui.uploads.complete("u1", done))).toMatchObject({
      url: "api/ui/uploads/u1/complete",
      method: "POST",
      body: done,
    });
  });

  it("covers jobs and garbage collection", async () => {
    expect(await call(() => ui.jobs())).toMatchObject({ url: "api/ui/jobs", method: "GET" });
    expect(await call(() => ui.gcRun())).toMatchObject({ url: "api/ui/gc/run", method: "POST" });
  });

  it("encodes path segments", async () => {
    expect(await call(() => ui.clips.get("a/b"))).toMatchObject({ url: "api/ui/clips/a%2Fb" });
  });
});

describe("messageOf()", () => {
  it("uses the API detail, the message of any other Error, or the stringified value", () => {
    expect(messageOf(new ApiError(409, "Collection already exists"))).toBe("Collection already exists");
    expect(messageOf(new Error("offline"))).toBe("offline");
    expect(messageOf("plain text")).toBe("plain text");
    expect(messageOf(42)).toBe("42");
    expect(messageOf(undefined)).toBe("undefined");
  });
});
