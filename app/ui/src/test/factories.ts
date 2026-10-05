// Plain builders for spec files (never imported by app code). Every field has a sensible default
// so a spec only states what it cares about.
import type { Clip, Collection, NormalizationProfile, Render, Season } from "@/api/types";

export function makeRender(patch: Partial<Render> = {}): Render {
  return {
    id: "render-1",
    n: 1,
    relative_path: "cinema-studio/renders/clip/clip-r1-render-1.mp4",
    media_path: "cinema-studio/renders/clip/clip-r1-render-1.mp4",
    size: 4_000_000,
    sha256: "0".repeat(64),
    duration: 12,
    content_start: 2,
    content_end: 10,
    lead_in: 2,
    tail_out: 2,
    content_duration: 8,
    timing_source: "measured",
    integrated_lufs: -18,
    true_peak: -1.5,
    recipe_hash: "recipe-hash",
    profile_fingerprint: "profile-fingerprint",
    published_at: "2026-10-03T10:00:00Z",
    ...patch,
  };
}

export function makeClip(patch: Partial<Clip> & { id: string }): Clip {
  return {
    collection_id: "regular",
    title: patch.id,
    source_name: `${patch.id}.mp4`,
    enabled: true,
    notes: "",
    original: {
      filename: `${patch.id}.mp4`,
      size: 8_000_000,
      sha256: "1".repeat(64),
      duration: 12,
      width: 1920,
      height: 1080,
      fps: 24,
      has_audio: true,
      video_codec: "h264",
    },
    recipe: {
      trim_start: 0,
      trim_end: null,
      crop: null,
      fade_in: null,
      fade_out: null,
      gain_db: 0,
      profile_id: null,
      lead_in: 2,
      tail_out: 2,
    },
    render: makeRender(),
    render_pending: false,
    status: "ready",
    error: null,
    needs_source: false,
    sort_key: patch.id,
    selection_count: 0,
    last_selected_at: null,
    has_preview: false,
    has_thumbs: true,
    created_at: "2026-10-03T10:00:00Z",
    updated_at: "2026-10-03T10:00:00Z",
    ...patch,
  };
}

export function makeCollection(patch: Partial<Collection> & { id: string }): Collection {
  return {
    name: patch.id,
    color: "#f59e0b",
    icon: "mdi:filmstrip-box",
    playback_mode: "random",
    order: [],
    processing_profile_id: "compatibility-4k-loudness",
    enabled: true,
    sort_order: 0,
    ...patch,
  };
}

export function makeSeason(patch: Partial<Season> & { id: string }): Season {
  return {
    name: patch.id,
    color: "#34d399",
    icon: "mdi:calendar-blank",
    start: null,
    end: null,
    priority: 0,
    collection_id: "regular",
    builtin: false,
    ...patch,
  };
}

export function makeNormProfile(patch: Partial<NormalizationProfile> & { id: string }): NormalizationProfile {
  return { name: patch.id, target_lufs: -16, true_peak: -1.5, lra: 11, ...patch };
}
