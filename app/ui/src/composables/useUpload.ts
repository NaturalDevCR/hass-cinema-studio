import { ref, watch, type Ref } from "vue";
import { ApiError, messageOf, ui } from "@/api/client";
import type { Clip, UploadComplete } from "@/api/types";
import { translate } from "@/i18n";
import { useStudio } from "./useStudio";
import { useJobs } from "./useJobs";

export type UploadItem = {
  id: string;
  file: File;
  status: "pending" | "uploading" | "processing" | "done" | "error";
  progress: number;
  error: string | null;
  clipId: string | null;
  retryable: boolean;
};
export type UploadDefaults = Omit<UploadComplete, "title">;
export const UPLOAD_EXTENSIONS = [".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".ts"];
const items: Ref<UploadItem[]> = ref([]);
const busy = ref(false);
const studio = useStudio();
let seq = 0;
let run: Promise<void> | null = null;
let pollTimer: ReturnType<typeof setTimeout> | undefined;

function validation(file: File): string | null {
  if (!UPLOAD_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext))) return translate("upload.unsupported");
  const limit = studio.state.value?.settings.max_upload_mb;
  if (limit !== undefined && file.size > limit * 1024 * 1024) return translate("upload.oversized", { n: limit });
  return file.size === 0 ? translate("upload.emptyFile") : null;
}

// Module state survives route changes. Only processing items need an extra clip poll:
// jobs may have finished before the job tray's first request was primed.
function schedule(): void {
  clearTimeout(pollTimer);
  if (!items.value.some((item) => item.status === "processing")) return;
  pollTimer = setTimeout(async () => {
    if (!document.hidden) await studio.refreshClips();
    schedule();
  }, 1500);
}
const confirming = new Set<UploadItem>();
function applyStatus(item: UploadItem, clip: Clip): void {
  if (clip.status === "ready") item.status = "done";
  if (clip.status === "failed") {
    item.status = "error";
    item.error = clip.error ?? translate("error.unknown");
    item.retryable = false;
  }
}
async function confirmMissing(item: UploadItem): Promise<void> {
  if (confirming.has(item)) return;
  confirming.add(item);
  const clipId = item.clipId!;
  const stillProcessing = () => items.value.includes(item) && item.status === "processing" && item.clipId === clipId;
  try {
    const clip = await ui.clips.get(clipId);
    if (stillProcessing()) applyStatus(item, clip);
  } catch (cause) {
    if (stillProcessing() && cause instanceof ApiError && cause.status === 404) {
      item.status = "error";
      item.error = translate("upload.clipRemoved");
      item.retryable = false;
    }
    // Transient failures leave the row processing for the next clip poll.
  } finally {
    confirming.delete(item);
    schedule();
  }
}
watch(studio.clips, (clips) => {
  const byId = new Map(clips.map((clip) => [clip.id, clip]));
  for (const item of items.value) {
    if (item.status !== "processing" || !item.clipId) continue;
    const clip = byId.get(item.clipId);
    if (clip) applyStatus(item, clip);
    else void confirmMissing(item);
  }
  schedule();
});

function add(files: FileList | File[]): void {
  for (const file of Array.from(files)) {
    const error = validation(file);
    items.value.push({
      id: `upload-${++seq}-${Date.now().toString(36)}`,
      file,
      status: error ? "error" : "pending",
      progress: 0,
      error,
      retryable: !error,
      clipId: null,
    });
  }
}

async function upload(item: UploadItem, body: UploadDefaults): Promise<void> {
  if (!items.value.includes(item)) return;
  item.error = validation(item.file);
  item.retryable = !item.error;
  if (item.error) {
    item.status = "error";
    return;
  }
  item.status = "uploading";
  try {
    const { upload_id, chunk_size } = await ui.uploads.create(item.file.name, item.file.size);
    if (!Number.isInteger(chunk_size) || chunk_size <= 0) throw new Error(translate("error.invalidResponse"));
    for (let offset = 0, index = 0; offset < item.file.size; offset += chunk_size, index++) {
      const end = Math.min(offset + chunk_size, item.file.size);
      await ui.uploads.chunk(upload_id, index, item.file.slice(offset, end));
      item.progress = end / item.file.size;
    }
    const clip = await ui.uploads.complete(upload_id, body);
    item.clipId = clip.id;
    item.status = "processing";
    schedule();
    await Promise.all([useJobs().refresh(), studio.refreshClips(), studio.refresh()]);
  } catch (cause) {
    item.status = "error";
    item.error = messageOf(cause);
  }
}

function start(defaults: UploadDefaults): Promise<void> {
  if (run) return run;
  if (!defaults.collection_id) return Promise.resolve();
  // Snapshot defaults: edits made during the upload affect the next batch only.
  const body = { ...defaults };
  const queue = items.value.filter((item) => item.status === "pending");
  busy.value = true;
  async function worker(): Promise<void> {
    for (let item = queue.shift(); item; item = queue.shift()) await upload(item, body);
  }
  run = Promise.all([worker(), worker()])
    .then(() => {})
    .finally(() => {
      busy.value = false;
      run = null;
    });
  return run;
}
function remove(id: string): void {
  items.value = items.value.filter((item) => item.id !== id || item.status === "uploading");
  schedule();
}
function retry(id: string): void {
  const item = items.value.find((item) => item.id === id);
  if (item?.status !== "error" || item.clipId) return;
  item.error = validation(item.file);
  item.retryable = !item.error;
  if (!item.error) {
    item.status = "pending";
    item.progress = 0;
  }
}
function clearDone(): void {
  items.value = items.value.filter((item) => item.status !== "done");
}
export function useUpload() {
  return { items, busy, add, start, remove, clearDone, retry };
}
