// Mirrors the "Shared API Reference" types verbatim (snake_case on the wire).
// Anything below the "UI API shapes" divider is derived from the endpoint table.

export type Season = {
  id: string;
  name: string;
  color: string;
  icon: string;
  start: string | null; // "MM-DD", inclusive; null only for regular
  end: string | null;
  priority: number;
  collection_id: string;
  builtin: boolean;
};

export type PlaybackMode = "random" | "sequential" | "custom";

export type Collection = {
  id: string;
  name: string;
  color: string;
  icon: string;
  playback_mode: PlaybackMode;
  order: string[];
  processing_profile_id: string;
  enabled: boolean;
  sort_order: number;
};

export type NormalizationProfile = {
  id: string;
  name: string;
  target_lufs: number;
  true_peak: number;
  lra: number;
};

/** Clips `ProcessingProfile.model_dump(mode="json")`, carried verbatim. */
export type ProcessingProfileSettings = {
  profile_version: number;
  video: {
    width: number;
    height: number;
    fps: number;
    codec: string;
    preset: string;
    quality: { mode: "crf"; crf: number; bitrate_kbps: null } | { mode: "bitrate"; bitrate_kbps: number; crf: null };
    h264_profile: string;
    level: string;
    pixel_format: string;
    scaling:
      | { strategy: "aspect_fit"; width: number; height: number; sar_num: number; sar_den: number }
      | { strategy: "crop"; width: number; height: number };
    fast_start: boolean;
    maxrate_kbps: number | null;
    bufsize_kbps: number | null;
    keyframe_interval_seconds: number | null;
  };
  audio: {
    codec: string;
    bitrate_kbps: number;
    channels: number;
    sample_rate: number;
    missing_policy: { mode: "required" } | { mode: "silence" };
    fallback: "none" | "silence";
    pad_or_trim: boolean;
  };
  loudness:
    | {
        mode: "two_pass";
        integrated_lufs: number;
        true_peak_dbtp: number;
        lra_lu: number;
        final_mix_normalization: boolean;
      }
    | { mode: "disabled"; final_mix_normalization: boolean };
  transitions: {
    type: "fade";
    duration_seconds: number;
    from_segment: "intro" | "clip" | "outro";
    to_segment: "intro" | "clip" | "outro";
  }[];
  fade_in_seconds: number;
  fade_out_seconds: number;
  output: { container: "mp4" | "mkv" | "webm"; extension: string; atomic_finalize: boolean; temporary_output: boolean };
  hardware_acceleration: boolean;
  decode_error_policy: "warn" | "fail";
  intro_reference: string | null;
  outro_reference: string | null;
  timeout_seconds: number;
  timeout_seconds_per_minute: number;
  minimum_segment_duration_seconds: number | null;
};

export type ProcessingProfile = { id: string; name: string; settings: ProcessingProfileSettings };

export type Asset = { filename: string; size: number | null; sha256: string | null; status: "ready" | "missing" };

export type Affected<K extends string, T> = { [P in K]: T } & { affected_clip_ids: string[] };

export type Crop = { x: number; y: number; w: number; h: number }; // source pixels

export type Recipe = {
  trim_start: number;
  trim_end: number | null;
  crop: Crop | null;
  fade_in: number | null; // null = processing profile fades
  fade_out: number | null;
  gain_db: number;
  profile_id: string | null; // normalization override
  lead_in: number; // margins (default 2.0 / 2.0)
  tail_out: number;
};

export type OriginalInfo = {
  filename: string;
  size: number;
  sha256: string;
  duration: number;
  width: number;
  height: number;
  fps: number | null;
  has_audio: boolean;
  video_codec: string;
};

export type Render = {
  id: string;
  n: number;
  relative_path: string; // "cinema-studio/renders/<clip_id>/<file>" (relative to /media)
  media_path: string;
  size: number;
  sha256: string;
  duration: number;
  content_start: number;
  content_end: number;
  lead_in: number;
  tail_out: number;
  content_duration: number;
  timing_source: "measured" | "legacy_worker" | "legacy_full_file";
  integrated_lufs: number | null;
  true_peak: number | null;
  recipe_hash: string;
  profile_fingerprint: string;
  published_at: string;
};

export type ClipStatus = "processing" | "ready" | "rendering" | "failed";

export type Clip = {
  id: string;
  collection_id: string;
  title: string;
  source_name: string;
  enabled: boolean;
  notes: string;
  original: OriginalInfo | null;
  recipe: Recipe;
  render: Render | null;
  render_pending: boolean;
  status: ClipStatus;
  error: string | null;
  needs_source: boolean;
  sort_key: string;
  selection_count: number;
  last_selected_at: string | null;
  has_preview: boolean;
  has_thumbs: boolean;
  created_at: string;
  updated_at: string;
};

export type JobKind = "probe" | "render" | "preview" | "thumbs" | "legacy_import";
export type JobStatus = "queued" | "running" | "done" | "failed";

export type Job = {
  id: string;
  kind: JobKind;
  clip_id: string | null;
  clip_title: string;
  status: JobStatus;
  progress: number; // fraction 0..1
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type TestTarget = { id: string; label: string; entity_id: string }; // media_player.* only

export type Settings = {
  max_upload_mb: number;
  max_duration_s: number;
  default_lead_in: number;
  default_tail_out: number;
  disk_reserve_bytes: number;
  test_targets: TestTarget[];
  protected_entities: string[];
};

export type ConsumerInfo = {
  consumer_id: string;
  last_seen_at: string | null;
  held_revision: number | null;
  file_present: boolean;
  pins: number;
};

export type LegacyReport = {
  run_id: string;
  started_at: string;
  finished_at: string | null;
  catalog_revision: number;
  imported: string[];
  queued_for_render: string[];
  needs_source: string[];
  skipped: { clip_id: string; reason: string }[];
  missing_assets: string[];
};

export type State = {
  version: string;
  api_token_masked: string;
  catalog_revision: number;
  discovery: { status: "ok" | "failed" | "unavailable"; message: string | null };
  storage: {
    free_bytes: number;
    originals_bytes: number;
    renders_bytes: number;
    retired_bytes: number;
    work_bytes: number;
    network_fs: boolean;
  };
  gc: { enabled: boolean; halted_reason: string | null; last_run_at: string | null; deleted_last_run: number };
  consumers: ConsumerInfo[];
  legacy_import: LegacyReport | null;
  settings: Settings;
};

// Integration API v1 catalog (bearer auth). The UI never calls it; kept for parity.
export type Catalog = {
  contract_version: 1;
  revision: number;
  instance_id: string;
  generated_at: string;
  seasons: Omit<Season, "builtin">[];
  collections: Omit<Collection, "sort_order" | "processing_profile_id">[];
  clips: {
    id: string;
    collection_id: string;
    title: string;
    source_name: string;
    enabled: boolean;
    sort_key: string;
    render_pending: boolean;
    render: Render;
  }[];
};

// ---------------------------------------------------------------------------
// UI API shapes (request/response bodies from the endpoint table)
// ---------------------------------------------------------------------------

export type CollectionInput = {
  id?: string;
  name: string;
  color?: string;
  icon?: string;
  playback_mode?: PlaybackMode;
  processing_profile_id?: string;
};
export type CollectionPatch = Partial<Omit<Collection, "id" | "order" | "sort_order">>;

export type SeasonInput = {
  id?: string;
  name: string;
  color?: string;
  icon?: string;
  start: string;
  end: string;
  priority?: number;
  collection_id: string;
};
export type SeasonPatch = Partial<Omit<Season, "id" | "builtin">>;
export type SeasonResolution = { date: string; season_id: string; collection_id: string };

export type NormalizationProfileInput = {
  id?: string;
  name: string;
  target_lufs: number;
  true_peak: number;
  lra: number;
};
export type NormalizationProfilePatch = Partial<Omit<NormalizationProfile, "id">>;
export type NormalizationApplyBody = { clip_ids: string[] } | { collection_id: string };

export type ProcessingProfileInput = { id?: string; name: string; settings: ProcessingProfileSettings };
export type ProcessingProfilePatch = { name?: string; settings?: ProcessingProfileSettings };

export type ClipPatch = Partial<Pick<Clip, "title" | "collection_id" | "enabled" | "notes">>;

export type BulkSet = {
  collection_id?: string;
  enabled?: boolean;
  /** Key present => set the normalization override and queue a render; `null` clears it. */
  profile_id?: string | null;
};
export type BulkBody = { ids: string[]; set: BulkSet };
export type BulkResult = { updated: number; queued: number };

export type TestSource = "preview" | "render";
export type TestBody = { target_id: string; source: TestSource };
export type TestResult = { ok: true; media_content_id: string };

export type GcResult = { deleted: number; halted_reason: string | null };

export type UploadInit = { upload_id: string; chunk_size: number };
export type UploadComplete = { collection_id: string; title?: string };

export type MediaKind = "original" | "preview" | "render";
