import { translate } from "@/i18n";
import type {
  Affected,
  Asset,
  BulkBody,
  BulkResult,
  Clip,
  ClipPatch,
  Collection,
  CollectionInput,
  CollectionPatch,
  GcResult,
  Job,
  MediaKind,
  NormalizationApplyBody,
  NormalizationProfile,
  NormalizationProfileInput,
  NormalizationProfilePatch,
  ProcessingProfile,
  ProcessingProfileInput,
  ProcessingProfilePatch,
  Recipe,
  Season,
  SeasonInput,
  SeasonPatch,
  SeasonResolution,
  Settings,
  State,
  TestBody,
  TestResult,
  UploadComplete,
  UploadInit,
} from "./types";

/** Failure reported by the Studio API (or `status: 0` when it could not be reached at all). */
export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Text for anything a request can throw, for inline errors: the API's `detail` for an
 * {@link ApiError}, the message of any other Error, otherwise the value as a string.
 */
export function messageOf(cause: unknown): string {
  if (cause instanceof ApiError) return cause.detail;
  return cause instanceof Error ? cause.message : String(cause);
}

type ApiInit = RequestInit & { json?: unknown };

/** Location prefixes FastAPI adds that say nothing about which field is wrong. */
const LOC_ROOTS = new Set(["body", "query", "path", "header", "cookie"]);

/** `{loc: ["body", "title"], msg: "Field required"}` -> "title: Field required". */
function describeIssue(item: unknown): string | null {
  if (typeof item === "string") return item || null;
  const { loc, msg } = (item ?? {}) as { loc?: unknown; msg?: unknown };
  if (typeof msg !== "string" || msg === "") return null;
  const field = Array.isArray(loc)
    ? [...loc].reverse().find((part) => typeof part === "string" && !LOC_ROOTS.has(part))
    : undefined;
  return field ? `${field}: ${msg}` : msg;
}

/** FastAPI sends `{detail: "text"}` or, for 422s, `{detail: [{loc, msg, ...}]}`. */
async function readDetail(response: Response): Promise<string> {
  const fallback = response.statusText || translate("error.http", { status: response.status });
  try {
    const body: unknown = await response.json();
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string" && detail) return detail;
    if (Array.isArray(detail)) {
      const messages = detail.map(describeIssue).filter((msg): msg is string => msg !== null);
      if (messages.length) return messages.join("; ");
    }
  } catch {
    // body was not JSON (proxy error page, empty body)
  }
  return fallback;
}

/**
 * Calls the Studio API. `path` is relative on purpose ("api/ui/clips"): behind
 * Home Assistant Ingress the app lives under an unknown prefix, so a leading
 * slash would escape it.
 */
export async function api<T>(path: string, init: ApiInit = {}): Promise<T> {
  const { json, headers: initHeaders, body, ...rest } = init;
  const headers = new Headers(initHeaders);
  if (!headers.has("accept")) headers.set("accept", "application/json");
  let payload = body;
  if (json !== undefined) {
    payload = JSON.stringify(json);
    if (!headers.has("content-type")) headers.set("content-type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(path.replace(/^\/+/, ""), { ...rest, headers, body: payload });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, translate("error.network"));
  }

  if (!response.ok) throw new ApiError(response.status, await readDetail(response));
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    // 2xx but not JSON: usually a proxy or Ingress page standing in for the API
    throw new ApiError(response.status, translate("error.invalidResponse"));
  }
}

const seg = encodeURIComponent;
const send = (method: string, json?: unknown): ApiInit => (json === undefined ? { method } : { method, json });

/** Every endpoint the UI uses, grouped like the API reference. */
export const ui = {
  state: () => api<State>("api/ui/state"),
  token: () => api<{ token: string }>("api/ui/token"),
  rotateToken: () => api<{ api_token_masked: string }>("api/ui/token/rotate", send("POST")),

  settings: {
    get: () => api<Settings>("api/ui/settings"),
    put: (settings: Settings) => api<Settings>("api/ui/settings", send("PUT", settings)),
  },

  collections: {
    list: () => api<Collection[]>("api/ui/collections"),
    create: (body: CollectionInput) => api<Collection>("api/ui/collections", send("POST", body)),
    update: (id: string, patch: CollectionPatch) =>
      api<Affected<"collection", Collection>>(`api/ui/collections/${seg(id)}`, send("PATCH", patch)),
    remove: (id: string) => api<void>(`api/ui/collections/${seg(id)}`, send("DELETE")),
    order: (id: string, clipIds: string[]) =>
      api<Collection>(`api/ui/collections/${seg(id)}/order`, send("PUT", { clip_ids: clipIds })),
  },

  seasons: {
    list: () => api<Season[]>("api/ui/seasons"),
    create: (body: SeasonInput) => api<Season>("api/ui/seasons", send("POST", body)),
    update: (id: string, patch: SeasonPatch) => api<Season>(`api/ui/seasons/${seg(id)}`, send("PATCH", patch)),
    remove: (id: string) => api<void>(`api/ui/seasons/${seg(id)}`, send("DELETE")),
    resolve: (date: string) => api<SeasonResolution>(`api/ui/seasons/resolve?date=${seg(date)}`),
  },

  normProfiles: {
    list: () => api<NormalizationProfile[]>("api/ui/normalization-profiles"),
    create: (body: NormalizationProfileInput) =>
      api<NormalizationProfile>("api/ui/normalization-profiles", send("POST", body)),
    update: (id: string, patch: NormalizationProfilePatch) =>
      api<Affected<"profile", NormalizationProfile>>(`api/ui/normalization-profiles/${seg(id)}`, send("PATCH", patch)),
    remove: (id: string) => api<void>(`api/ui/normalization-profiles/${seg(id)}`, send("DELETE")),
    apply: (id: string, body: NormalizationApplyBody) =>
      api<{ queued: number }>(`api/ui/normalization-profiles/${seg(id)}/apply`, send("POST", body)),
  },

  procProfiles: {
    list: () => api<ProcessingProfile[]>("api/ui/processing-profiles"),
    create: (body: ProcessingProfileInput) =>
      api<ProcessingProfile>("api/ui/processing-profiles", send("POST", body)),
    update: (id: string, patch: ProcessingProfilePatch) =>
      api<Affected<"profile", ProcessingProfile>>(`api/ui/processing-profiles/${seg(id)}`, send("PATCH", patch)),
    remove: (id: string) => api<void>(`api/ui/processing-profiles/${seg(id)}`, send("DELETE")),
  },

  assets: {
    list: () => api<Asset[]>("api/ui/assets"),
    upload: (file: File) => {
      const form = new FormData();
      form.append("file", file, file.name);
      return api<Affected<"asset", Asset>>("api/ui/assets", { method: "POST", body: form });
    },
    remove: (filename: string) => api<void>(`api/ui/assets/${seg(filename)}`, send("DELETE")),
  },

  clips: {
    list: () => api<Clip[]>("api/ui/clips"),
    get: (id: string) => api<Clip>(`api/ui/clips/${seg(id)}`),
    update: (id: string, patch: ClipPatch) => api<Clip>(`api/ui/clips/${seg(id)}`, send("PATCH", patch)),
    putRecipe: (id: string, recipe: Recipe) =>
      api<{ clip: Clip; job: Job }>(`api/ui/clips/${seg(id)}/recipe`, send("PUT", recipe)),
    preview: (id: string, recipe: Recipe) =>
      api<{ job: Job }>(`api/ui/clips/${seg(id)}/preview`, send("POST", recipe)),
    rerender: (id: string) => api<{ job: Job }>(`api/ui/clips/${seg(id)}/rerender`, send("POST")),
    remove: (id: string) => api<void>(`api/ui/clips/${seg(id)}`, send("DELETE")),
    bulk: (body: BulkBody) => api<BulkResult>("api/ui/clips/bulk", send("POST", body)),
    test: (id: string, body: TestBody) =>
      api<TestResult>(`api/ui/clips/${seg(id)}/test`, send("POST", body)),
    /** Source repair: swap in a fully uploaded file (see `uploads`) instead of completing it as a new clip. */
    replaceSource: (id: string, uploadId: string) =>
      api<Clip>(`api/ui/clips/${seg(id)}/source`, send("POST", { upload_id: uploadId })),
  },

  uploads: {
    create: (filename: string, size: number) =>
      api<UploadInit>("api/ui/uploads", send("POST", { filename, size })),
    chunk: (id: string, index: number, blob: Blob) =>
      api<{ received: number }>(`api/ui/uploads/${seg(id)}/chunks/${index}`, {
        method: "PUT",
        body: blob,
        headers: { "content-type": "application/octet-stream" },
      }),
    complete: (id: string, body: UploadComplete) =>
      api<Clip>(`api/ui/uploads/${seg(id)}/complete`, send("POST", body)),
  },

  jobs: () => api<Job[]>("api/ui/jobs"),
  gcRun: () => api<GcResult>("api/ui/gc/run", send("POST")),
};

const withBust = (base: string, bust?: string | number): string =>
  bust === undefined || bust === "" ? base : `${base}?v=${seg(String(bust))}`;

/** Relative URL of a clip's video. `bust` (e.g. the render id) defeats stale browser caches. */
export function mediaUrl(id: string, kind: MediaKind, bust?: string | number): string {
  return withBust(`api/ui/clips/${seg(id)}/${kind}`, bust);
}

/** Relative URL of a clip's poster frame. */
export function posterUrl(id: string, bust?: string | number): string {
  return withBust(`api/ui/clips/${seg(id)}/poster.jpg`, bust);
}

/** Relative URL of one frame of the original's filmstrip (`index` from 0 to `count - 1`). */
export function filmstripUrl(id: string, index: number, bust?: string | number): string {
  return withBust(`api/ui/clips/${seg(id)}/filmstrip/${index}.jpg`, bust);
}
