import type { State } from "@/api/types";

export const makeState = (): State => ({
  version: "1",
  api_token_masked: "••••abcd",
  catalog_revision: 1,
  discovery: { status: "ok", message: null },
  storage: {
    free_bytes: 50_000_000_000,
    originals_bytes: 2048,
    renders_bytes: 1024,
    retired_bytes: 512,
    work_bytes: 0,
    network_fs: false,
  },
  gc: { enabled: true, halted_reason: null, last_run_at: null, deleted_last_run: 0 },
  consumers: [],
  legacy_import: null,
  settings: {
    max_upload_mb: 2048,
    max_duration_s: 7200,
    default_lead_in: 2,
    default_tail_out: 2,
    disk_reserve_bytes: 5_000_000_000,
    test_targets: [],
    protected_entities: ["media_player.otocuma_dp", "cover.ocl_screen_projector"],
  },
});
