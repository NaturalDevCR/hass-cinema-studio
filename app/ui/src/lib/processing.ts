import type { ProcessingProfileSettings } from "@/api/types";

export type Transition = ProcessingProfileSettings["transitions"][number];
export type ResolutionPreset = "4k" | "1080p" | "720p";
export type ResolutionChoice = ResolutionPreset | "custom";

export const RESOLUTION_PRESETS: Record<ResolutionPreset, { width: number; height: number }> = {
  "4k": { width: 3840, height: 2160 },
  "1080p": { width: 1920, height: 1080 },
  "720p": { width: 1280, height: 720 },
};

/** Clips `ProcessingProfile()` defaults, as `model_dump(mode="json")` returns them. */
export const DEFAULT_PROCESSING_SETTINGS: ProcessingProfileSettings = {
  profile_version: 1,
  video: {
    width: 3840,
    height: 2160,
    fps: 24,
    codec: "libx264",
    preset: "fast",
    quality: { mode: "crf", crf: 23, bitrate_kbps: null },
    h264_profile: "high",
    level: "5.1",
    pixel_format: "yuv420p",
    scaling: { strategy: "aspect_fit", width: 3840, height: 2160, sar_num: 1, sar_den: 1 },
    fast_start: true,
    maxrate_kbps: null,
    bufsize_kbps: null,
    keyframe_interval_seconds: null,
  },
  audio: {
    codec: "aac",
    bitrate_kbps: 192,
    channels: 2,
    sample_rate: 48000,
    missing_policy: { mode: "required" },
    fallback: "none",
    pad_or_trim: true,
  },
  loudness: {
    mode: "two_pass",
    integrated_lufs: -18,
    true_peak_dbtp: -1.5,
    lra_lu: 11,
    final_mix_normalization: true,
  },
  transitions: [
    { type: "fade", duration_seconds: 1, from_segment: "intro", to_segment: "clip" },
    { type: "fade", duration_seconds: 1, from_segment: "clip", to_segment: "outro" },
  ],
  fade_in_seconds: 1,
  fade_out_seconds: 1.5,
  output: { container: "mp4", extension: "mp4", atomic_finalize: true, temporary_output: true },
  hardware_acceleration: false,
  decode_error_policy: "warn",
  intro_reference: null,
  outro_reference: null,
  timeout_seconds: 300,
  timeout_seconds_per_minute: 120,
  minimum_segment_duration_seconds: null,
};

export const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

export function resolutionOf(video: ProcessingProfileSettings["video"]): ResolutionChoice {
  for (const [key, size] of Object.entries(RESOLUTION_PRESETS)) {
    if (video.width === size.width && video.height === size.height) return key as ResolutionPreset;
  }
  return "custom";
}

/** The video size and the scaling target move together: the scaler is what actually sizes the output. */
export function applyResolution(settings: ProcessingProfileSettings, preset: ResolutionPreset): void {
  const { width, height } = RESOLUTION_PRESETS[preset];
  settings.video.width = width;
  settings.video.height = height;
  settings.video.scaling.width = width;
  settings.video.scaling.height = height;
}

type Edge = "intro" | "outro";
const isEdge = (transition: Transition, edge: Edge) =>
  edge === "intro"
    ? transition.from_segment === "intro" && transition.to_segment === "clip"
    : transition.from_segment === "clip" && transition.to_segment === "outro";

export function transitionSeconds(settings: ProcessingProfileSettings, edge: Edge): number | null {
  return settings.transitions.find((t) => isEdge(t, edge))?.duration_seconds ?? null;
}

/** `null` (an empty field) removes the transition; a number updates it in place or adds it. */
export function setTransitionSeconds(settings: ProcessingProfileSettings, edge: Edge, seconds: number | null): void {
  const index = settings.transitions.findIndex((t) => isEdge(t, edge));
  if (seconds === null) {
    if (index >= 0) settings.transitions.splice(index, 1);
  } else if (index >= 0) {
    settings.transitions[index]!.duration_seconds = seconds;
  } else {
    settings.transitions.push({
      type: "fade",
      duration_seconds: seconds,
      from_segment: edge === "intro" ? "intro" : "clip",
      to_segment: edge === "intro" ? "clip" : "outro",
    });
  }
}
