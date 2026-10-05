# Cinema Studio — Home Assistant App + HACS integration

Status: approved by Claude ⇄ GPT-6.1-Sol consensus on 2026-10-05 (user asleep,
approval delegated; review log in `docs/decisions/`).
Inputs: `docs/handoff/2026-10-05-brainstorm-handoff.md`, Sol critique
(`docs/decisions/2026-10-05-sol-critique-1.md`), production inspection on
2026-10-05 01:00 CST.

## Problem

Cinema clips at bar Otocuma run on `hass-clips-manager` (App "Cinema
Collections Worker" 1.11.0 + integration `cinema_collections`). It works, but:

- Pairing needs a manual bearer secret.
- `select_next_clip` calls the Worker live; Worker down = no cinema.
- Two season authorities disagree today (`sensor.active_collection` =
  `halloween` from Worker schedule; `sensor.temporada_de_cine_activa` =
  `regular` from HA templates). The script follows the HA one.
- Compiled output is overwritten in place (`jobs.py:_publish`, same path), so
  cached metadata can describe old bytes at a current path.
- The projector script double-checks timing through
  `shell_command.cinema_clip_metadata` because the service response is not
  trusted.
- Editing is limited (trim/crop); no loudness, fades, thumbnails, or device test.

Sound Effects (`hass-sound-effects`) solved the same class of problems for
audio and the user loves its flow and UI.

## Goals

- Same architecture and UI system as Sound Effects, specialized for video.
- Selection keeps working with the App stopped, updating, or crashed.
- A selection response trustworthy enough to retire
  `shell_command.cinema_clip_metadata`.
- Native seasons with an override select; entering a season restarts ordered
  playback at the first clip.
- Keep playback modes `random` (no-repeat rounds), `sequential`, `custom`.
- Editor: trim, crop, fades, loudness normalization (LUFS profiles), poster
  and filmstrip, test playback on a chosen `media_player`.
- Migrate production with one-step rollback at every stage; never change
  projector, screen, A/V, Snapcast, or lighting steps.

## Non-goals (v1)

- Playing media from the integration (automations stay the device layer).
- Weighted random, per-clip schedules, analytics beyond counters.
- Uninstalling the old product (left to the user after observation).

## Production facts this design must honour

- Sessions run every 30 min in the evening (`script.cinema_sesion` →
  `script.cinema_reproducir`). Callers/referrers of `cinema_reproducir`:
  `script.cinema_sesion`, `script.cinema_abortar`,
  `script.cinema_streaming_iniciar`, `automation.cinema_recuperar_sesion_huerfana`.
- Current response (trace 2026-10-05 03:30Z): `collection_id`, `clip_id`,
  `relative_output_path` (`regular/<clip_id>.mp4`), `media_content_id`
  (`media-source://media_source/local/cinema-collections/compiled/regular/<clip_id>.mp4`),
  `media_content_type: video`, `duration_seconds`, `duration`,
  `content_duration`, `lead_in_duration`, `tail_out_duration`,
  `content_start_offset`, `content_end_offset`, `history_reset`,
  `output_is_stale`. No `title`.
- Shell metadata returns `{ok, clip_id, duration, start, end, lead, tail,
  content_duration, timing_valid, relative_output_path, name}`; the script
  uses `duration/start/end/lead/tail/name` and checks `ok`, `clip_id`,
  `relative_output_path`.
- The script confirms playback by `clip_id in media_player.media_content_id`
  and anchors timing to observed Cast playback (`inicio` set after
  confirmation; `av_show`/`av_finish` read the Cast position). So every
  media URI must contain the `clip_id`; startup latency is already handled.
- Early close is enabled only when `tail >= 1.0`; `start <= 0` releases A/V
  immediately. Zero margins are therefore a legitimate, explicit value.
- Seasons: `input_select.cinema_temporada_de_clips` (`Automático por fecha`,
  `Regular`, `Halloween`, `Christmas`) over `sensor.temporada_por_fecha`
  (Halloween 10-31…10-31, Christmas 12-01…01-06, Christmas wins, else
  regular). Worker collections: `regular`, `halloween` (no `christmas`; the
  script falls back to `regular`).
- Data: 45 clips (44 ready, 1 stale). Files under
  `/media/cinema-collections/{source,compiled}`. Worker clip ids are UUIDs.
- `automation.pre_compile_cinema_clips` (03:00) and
  `automation.cinema_clips_reiniciar_historial_al_cambiar_de_temporada`.

## Architecture

New public repo `NaturalDevCR/hass-cinema-studio`, layout copied from
Sound Effects:

```
app/                               Supervisor App "Cinema Studio" (slug cinema_studio)
  src/cinema_studio/               FastAPI + SQLite + ffmpeg/ffprobe
  ui/                              Vue 3 + Vite + Tailwind 4 SPA (Ingress)
custom_components/cinema_studio/   HACS integration
contract/openapi-v1.yaml           App ⇄ integration contract
tests/  scripts/verify.sh  docs/  hacs.json  repository.yaml
```

Boundaries:

- **App** owns originals, recipes, renders (publication + retirement),
  collections, seasons, profiles, settings, statistics.
- **Integration** owns the persisted catalog snapshot, file verification,
  season resolution + activation, selection, and history.
- **Automations** own playback and devices.

## Media layout and publication (immutable renders)

Root `/media/cinema-studio/` (App maps `media:rw`; HA core sees it as
`media_dirs.local`):

- `originals/<clip_id>/<original_name>` — never modified after import/upload.
  Import from the old Worker uses a hard link when on the same filesystem
  (no extra space; the old Worker's in-place source edits create a new inode
  and do not touch ours), else a copy.
- `renders/<clip_id>/<clip_id>-r<n>-<render_uuid>.mp4` (full UUID4 hex) —
  immutable, never reused. `n` is a human-readable counter; uniqueness comes
  from the random `render_uuid` (a DB restore that rolls `n` back cannot
  collide). Files are created exclusively (`os.link` fails on an existing
  name; on that impossible collision a new UUID is drawn).
  URI: `media-source://media_source/local/cinema-studio/renders/<clip_id>/<file>`
  (contains `clip_id`).
- `consumers/<consumer_id>.json` + `.lock` — written by the integration (see GC).
- `.gc.lock` — `flock` fence between App GC and integration selection.
- `.work/` — temp, previews, thumbnails staging (not published).
- Thumbnails (App only): `/data/thumbs/<clip_id>/original/` (poster + filmstrip of
  the original timeline, used by the editor) and `/data/thumbs/<clip_id>/r<n>/poster.jpg`
  (poster of each published render).

Publication sequence (one worker, in-process queue, ported from Clips):

1. Render to `.work/<job>/out.mp4`; ffprobe; verify Cast profile; compute
   timing; compute size + sha256 (streamed).
2. Validate timing invariants (below). Fail = job fails, previous render
   stays published.
3. `fsync` the staged file, `os.link` it to the new render name (exclusive;
   staging and renders share `/media`), `fsync` the directory, unlink the
   staged path.
4. One SQLite transaction: insert render row, point clip's
   `published_render_id` at it, mark previous render `retired` with the new
   catalog revision, bump `catalog_revision`.
5. Fire `cinema_studio_catalog_changed` via Supervisor Core proxy.

Crash recovery on start:

- `.work/` staging files are never published; they are deleted on start.
- A committed file in `renders/` without a DB row (e.g. App `/data`
  restored from an older backup) stays at its path, is recorded as an
  `unrecognized` render (never selectable, not in the catalog), and is only
  ever deleted by GC under exactly the same rules as a retired render
  (age taken from the file's mtime).
- A DB render row whose file is missing → `missing`; the clip falls back to
  its newest earlier render that still exists, else `failed` (excluded).

Import of existing outputs is **staged** (see Import): every Worker
original and compiled output is first hard-linked into a private
`.work/import/<run_id>/` (not in `renders/`, not in the catalog). For each
staged file the App computes `sha256:size` and requires:

- compiled output == Worker `metadata.output_fingerprint` (the Worker writes
  it in the same DB update as the timing, so a match proves the timing
  belongs to these bytes); raw Worker timing (`metadata.*_seconds`, not the
  API's zero-filled fallbacks) passes our invariants; our ffprobe duration
  matches `output_duration_seconds` within 0.05 s;
- original == Worker `metadata.source_fingerprint`.

Then it re-fetches the Worker manifest and reconciles: any clip whose
`updated_at`, `output_fingerprint`, or `source_fingerprint` changed since
the first fetch is dropped from this run. Only after reconciliation, in one
DB transaction per clip, accepted files are linked (exclusive) to their
final `originals/` and `renders/` names and published as `r1`
(`timing_source: legacy_worker`), then the catalog revision bumps once.
Staged files are removed at the end of the run. A clip whose output fails
the checks but whose original passes is imported without a render and
queued for a fresh render with standard margins; a clip whose original
fails is imported with `needs_source` (its verified render may still
publish; editing is disabled until the user re-imports or uploads the
source). `legacy_full_file` (start 0, end = duration) is used only when the
output fingerprint matches and the raw Worker metadata has **no** timing
fields at all (the Worker's own legacy rule); never inferred from a
mismatch. If a published render ever has to be withdrawn, it goes through
normal retirement/GC — never moved or quarantined. This keeps the exact
bytes Cast plays today.

### Retirement / GC (shared filesystem fence)

Both processes see the same `/media` (bind mounts of one host directory on
one kernel), so coordination uses the filesystem, not HTTP — it works with
the App or the network down.

- **Consumer file** `consumers/<consumer_id>.json` (`consumer_id` = the
  integration's config entry id), replaced atomically (write temp, fsync,
  `os.replace`, fsync dir) by the integration only while holding the
  **shared** lock on `.gc.lock`. Content: `{consumer_id, generation (UUID
  per HA start), seq (monotonic within generation), written_at,
  held_revision, held_render_ids[] (every render id in the integration's
  current snapshot), pins[{render_id, expires_at}]}`.
- **Selection** (integration): take the shared lock (non-blocking retries,
  max 5 s, in executor) → `stat`-verify the chosen render → write the
  consumer file with the new pin (6 h) → release → commit history and
  return. Lock timeout or write failure → `ServiceValidationError
  not_ready` (the script then takes its fallback path); no unpinned
  selection is ever returned.
- **Writer serialization**: every consumer-file write is
  read-merge-write under an in-process `asyncio.Lock` **and** an exclusive
  `flock` on `consumers/<consumer_id>.lock` (taken before the shared
  `.gc.lock`). Merge rule: pins = union of on-disk unexpired pins and the
  integration's persisted pins (also kept in its `Store`), keeping the later
  `expires_at` per render; pins are never shortened or dropped before expiry,
  including pins for renders no longer in the snapshot. `held_render_ids` is
  replaced (it describes the current snapshot only).
- **Snapshot adoption** (integration, startup and every new catalog): under
  the locks above, rewrite the consumer file with the new `held_render_ids`
  (pins merged) before the snapshot becomes selectable. A restored HA backup therefore
  re-declares its old snapshot's renders before any selection; renders
  already deleted fail the `stat` check and are excluded.
- **GC** (App, hourly): take the **exclusive** lock; read every consumer
  file; delete a retired or `unrecognized` render only if it is in no
  consumer's `held_render_ids`, unpinned (pins compared with `expires_at`
  on the shared host clock; a pin also protects 10 min past expiry), and
  retired/unrecognized ≥ 48 h. Release. Holds the lock only while deleting.
- Halts: no consumer file for a consumer the App has served in the last 30
  days; a consumer file that fails to parse; `/media` is a network
  filesystem (flock unreliable — detected at start, GC disabled, banner).
- HTTP reports (`X-Cinema-Consumer`, selections) feed stats and the System
  view only; GC never depends on them.

Disk: new renders are refused when free space minus the job's estimated
output size (bitrate × duration × 1.2, plus the same again for staging) is
below `disk_reserve_bytes` (default 2 GiB). Disk pressure never triggers
early deletion.

## Data model (App, SQLite)

- `Collection`: `id` (slug, immutable; import keeps `regular`, `halloween`),
  `name`, `color`, `icon`, `playback_mode` (`random|sequential|custom`),
  `order` (clip ids, for `custom`), `processing_profile_id`, `enabled`.
- `Season`: `id`, `name`, `color`, `icon`, `start`/`end` (`MM-DD`,
  inclusive, may wrap), `priority`, `collection_id` (which collection plays
  in that season). Built-in `regular` (no range, fallback, plays
  `regular`).
- `ProcessingProfile`: ported verbatim from Clips
  (`profile_validation.ProcessingProfile`: video/audio encode settings,
  scaling, two-pass loudness, clip fade in/out, intro/outro asset references,
  intro→clip / clip→outro transitions, timeouts). Production uses
  `4k-loudness-with-intro` (3840×2160@24 libx264 crf 23, maxrate 20 Mb/s,
  AAC 192k 48 kHz, −18 LUFS/−1.5 dBTP/LRA 11, intro+outro
  `treebu-hotels-intro.mp4`, 1 s transitions, fades 1/1.5 s); import copies
  it with the same id. Each collection has `processing_profile_id`.
- `Asset`: intro/outro files under `/media/cinema-studio/assets/`. The old
  Worker keeps assets in its private `/data/assets` (unreachable), so import
  records referenced assets as `missing`; imported renders already contain
  them, and only a new render with that profile is blocked (clear error +
  UI prompt to upload the asset) until the user provides the file.
- `NormalizationProfile`: named loudness presets as Sound Effects
  (`standard -16`, `loud -13`, `soft -20`, `voice -18`, plus imported
  `cinema -18`). A clip recipe may set `profile_id` to override the
  processing profile's loudness target for that clip; null = profile's own.
- `Clip`: `id` (UUID; imports keep the Worker id), `collection_id`, `title`,
  `source_name`, `enabled`, `notes`, `original` (probe data),
  `recipe`, `published_render_id`, `status`
  (`processing|ready|rendering|failed`), `error`, `selection_count`,
  `last_selected_at`, `sort_key` (for `sequential`: import keeps Worker's
  sequential key).
- `Recipe`: `trim_start`, `trim_end`, `crop` (`{x,y,w,h}` or null),
  `fade_in`, `fade_out` (video+audio, inside the content region),
  `gain_db`, `profile_id` (normalization override), `lead_in` / `tail_out`
  (black/silent margins, default 2.0 s each, from settings). Clip fades in
  the recipe default to null = use the processing profile's fades.
- `Render`: `id` (= `render_uuid`), `clip_id`, `n`, `relative_path`, `size`, `sha256`,
  `duration`, `content_start`, `content_end`, `lead_in`, `tail_out`,
  `content_duration`, `timing_source` (`measured|legacy_worker|legacy_full_file`),
  `integrated_lufs`, `true_peak`, `recipe_hash`, `profile_fingerprint`,
  `state` (`published|retired|unrecognized|missing|deleted`), `published_at`,
  `retired_at`, `retired_revision`.
- `catalog_revision` integer.

## Timing invariants (validated at publish and again by the integration)

All values seconds, floats rounded to 3 decimals (millisecond grid).

- `0 < duration <= 7200`.
- `content_start == lead_in`, `0 <= content_start < content_end <= duration`.
- `abs(content_duration - (content_end - content_start)) <= 0.001`.
- `abs(tail_out - (duration - content_end)) <= 0.001`.
- Render pipeline: margins are pure black frames + digital silence; fades
  live inside the content region; `duration` is ffprobe container duration of
  the published file; `content_start/end` derive from frame-aligned margin
  frame counts (`frames / fps`, ported from Clips) and are checked against
  encoder output in tests (intro/outro detection on fixtures, ±1 frame).

A render that violates any invariant is never published (App) and never
selected (integration; logged + repair issue).

## Integration API v1 (`contract/openapi-v1.yaml`)

- `GET /api/v1/health` → `{status, version, api_version: 1, instance_id}`.
- Every v1 request carries `X-Cinema-Consumer: <entry_id>`; catalog polls
  carry `If-None-Match` (held revision). Used for stats/System view only.
- `GET /api/v1/catalog` →
  `{contract_version: 1, revision, instance_id, generated_at, seasons[],
  collections[], clips[]}`; each clip carries its published render (all
  render fields above + `relative_path`, `media_path` relative to
  `media_dirs.local`), plus `render_pending` (recipe changed, new render in
  queue). Clips without a published render are omitted.
- `POST /api/v1/selections` → `{events[{selection_id, clip_id, render_id,
  catalog_revision, selected_at}]}`; updates stats; integration retries from
  a persisted queue.
- `POST /api/v1/import/legacy` → body: legacy manifest from the old
  integration (see Import); returns a reconciliation report.

Auth: bearer token from discovery (`/data/api_token`), Ingress-IP check for
UI — identical to Sound Effects.

## Integration `cinema_studio`

Setup, discovery, options flow, persisted snapshot, coordinator (event +
30 s poll), connectivity binary sensor — as Sound Effects.

### File verification (offline-safe)

- On snapshot load (startup) and on each new snapshot, an executor job
  `stat`s every published render under `media_dirs.local` and records
  `verified = exists and size == render.size`. Hashes are not recomputed in
  HA (exclusive App ownership + immutable names make size + path sufficient;
  sha256 is for diagnostics and the App's own audits).
- At selection, the chosen candidate is `stat`ed again (executor) before
  history is committed; failure → mark unverified, drop from candidates,
  retry the pick (bounded by candidate count).
- A path passes only if it resolves (after `realpath`) inside
  `<media_dirs.local>/cinema-studio/renders/`, is a regular file (no
  symlinks), and its size equals the catalog size. `file_verified` means
  exactly this (existence + containment + size), not hash integrity; the
  guarantee rests on exclusive App ownership of `renders/` and immutable
  UUID names.
- Selection is enabled only after the snapshot, history and verification are
  restored; before that the action raises `not_ready`.

### Season resolution and activation

Effective season, first match: action `season` field → `select.cinema_studio_season_override`
(not `Auto`) → optional `season_entity` option → App calendar at local
date → `regular`. The season's `collection_id` is the collection to play;
a missing/empty/all-unverified collection falls back to the `regular`
season's collection with `season_fallback: true`; still nothing →
`ServiceValidationError no_playable_clip`.

Activation, persisted: the integration stores `last_effective_season`
and `last_effective_collection` (resolved without a per-call `season`
field). Rules, evaluated under the selection lock at selection time, when
the override select or `season_entity` changes, and at local midnight:

- Season changed and the new season resolves to its own collection without
  fallback → reset that collection's history once, store both values.
- Season changed but the new season fell back (missing/empty collection) →
  store values, no reset (today's automation skips unknown collections).
- Season unchanged but its mapped collection changed (user remapped in the
  App) → reset the new collection once.
- Restart without a change → nothing. A change that happened while HA was
  down is applied on the first evaluation after start. A whole season that
  started and ended during downtime is undetectable by endpoint comparison
  (accepted; same as today).
- `dry_run` and per-call `season` never read-modify-write activation.

### Selection (ported semantics)

Ported verbatim from `cinema_collections/history.py` (played-set
semantics):

- Each collection has `{round_number, played_clip_ids, last_selected_clip_id,
  last_reset_at, reset_pending}`. Eligible = candidates in mode order
  (`random`: any order; `sequential`: `sort_key`; `custom`: collection
  `order` then remaining by `sort_key`). `played` is filtered to eligible.
  `remaining = eligible − played` in mode order; if empty → new round
  (`round_number+1`, `history_reset: true`, played cleared).
- `random` picks uniformly (SystemRandom) from `remaining`; `sequential` and
  `custom` take `remaining[0]` (first unplayed in order — so reorders and
  reappearing clips behave exactly as today).
- Reset modes `on_exhaustion` (default) and `daily` (`reset_time`) as today.
- History persisted with `Store` and saved **before** the action returns
  (no delayed save; matches Clips). `asyncio.Lock` serializes selection and
  snapshot swaps.
- `dry_run` returns the pick without mutating.
- History import runs only after the catalog import (step 4 of Import):
  read-only load of `cinema_collections.<old_entry_id>.playback_history`,
  ids mapped 1:1 (import keeps Worker clip ids), unknown ids dropped.
  `last_effective_season/collection` are seeded from the current effective
  season so the cut-over does not reset. `import_legacy` with
  `history_only: true` refreshes it again at cut-over.

### Actions

`cinema_studio.select_next_clip` (`SupportsResponse.OPTIONAL`), fields
`collection_id` (optional; bypasses season mapping), `season`, `dry_run`.
Response (flat; superset of today's):

```
contract_version: 1
instance_id, catalog_revision, selection_id (uuid4), selected_at
collection_id, season, requested_season, season_source, season_fallback
playback_mode, history_reset, activation_reset
clip_id, title, source_name, render_id, render_n
relative_output_path      # cinema-studio/renders/<clip_id>/<clip_id>-r<n>-<render_uuid>.mp4
media_content_id          # media-source URI, contains clip_id
media_content_type: video
duration_seconds, duration                       # equal
content_duration, lead_in_duration, tail_out_duration,
content_start_offset, content_end_offset
timing_source, timing_verified: true, file_verified: true
render_pending, output_is_stale (= render_pending, compat)
size, sha256
```

Guarantee: every field describes one immutable published render that
passed the invariants and the file check within this call. Unknown timing
is never returned; such clips are not selectable. All numbers are finite
(NaN/inf rejected at parse), rounded once by the App at publish to 3
decimals; invariants use tolerance 0.001 on the rounded values; the
integration re-validates and never re-rounds. `timing_verified: true` means
provenance is `measured` or `legacy_worker`/`legacy_full_file` per the
import rules **and** the invariants passed. `profile_fingerprint` (hash of
normalization + Cast profile + recipe) is included. The integration emits
only `contract_version: 1`; consumers must reject other versions. Errors are
`ServiceValidationError` with translation keys `not_ready`,
`no_playable_clip`, `unknown_collection`, `unknown_season`.

`cinema_studio.reset_history` (`collection_id` optional), `cinema_studio.refresh`,
`cinema_studio.import_legacy` (`history_only` optional; see Import).

### Entities

`sensor.cinema_studio_active_season` (attrs `source`, `collection_id`,
`last_effective_season`), `select.cinema_studio_season_override` (`Auto` + season
names, restored), `sensor.cinema_studio_<collection>_last`,
`sensor.cinema_studio_catalog` (revision, clip counts, unverified count),
`binary_sensor.cinema_studio_studio_connected`. Diagnostics redact the
token.

## Import from the old product

`cinema_studio.import_legacy` (integration service, idempotent):

1. Reads the old `cinema_collections` config entry (same HA) and uses its
   stored `endpoint`/`token` to fetch clips, collections (mode, order),
   processing profiles, assets,
   and Worker status — no credential handling by people or tools.
   Quiescence is enforced for the whole operation: refuses to start unless
   the Worker reports no queued/active jobs and it is not within 03:00–03:30
   (nightly compile); staging, verification and the post-staging manifest
   reconciliation happen before anything is published (see "Import of
   existing outputs is staged"); changed clips are simply skipped and
   reported for a re-run.
2. Posts a manifest to `POST /api/v1/import/legacy`. The App hard-links
   sources and compiled outputs (`r1`), keeps clip ids, collection ids,
   modes, custom order, sequential keys, titles (`source_name` stem), and
   creates seasons Regular / Halloween (10-31…10-31, prio 10) / Christmas
   (12-01…01-06, prio 20, collection `regular` until a `christmas`
   collection exists) from the manifest's season block (taken from the
   `input_datetime.party_*` helpers by the service).
3. Report: imported, skipped (stale without output, missing files),
   timing mismatches. Re-running updates nothing already imported.
4. The integration imports history (above).

## UI (Vue 3, Tailwind 4) — port of Sound Effects UI system

NavBar (bottom on phones, sidebar ≥ md), Sheet, ConfirmDialog, Toast, Icon,
en/es i18n, dark-first, accent amber `#f59e0b` (distinct from Sound
Effects violet).

1. **Library** — collection chips with counts, season filter, search; clip
   cards with poster, duration, render status, LUFS, pending badge; drag
   reorder in `custom` collections (ported visual-order UI); bulk move,
   enable/disable, profile apply.
2. **Editor** — video player of original/preview/published; filmstrip
   timeline (thumbnails every N s) with trim handles; crop box overlay;
   fade in/out; gain; LUFS profile; margins; "Preview render" (writes
   `.work/previews`, plays in browser); "Test on device" (picker of
   `media_player` entities from settings; App calls `media_player.play_media`
   with the preview or published URI; the App refuses entities listed in
   `protected_entities`, default `media_player.otocuma_dp`,
   `cover.ocl_screen_projector`, `remote.*`, and never touches anything else);
   "Save & publish".
3. **Upload** — chunked uploads (4 MB), per-batch collection/profile.
4. **Organize** — collections (mode, order), seasons timeline with date
   probe, normalization and Cast profiles.
5. **System** — connection/discovery, storage (free space, renders,
   retired pending GC), jobs, test targets, legacy import status.

## Error handling

- App down: selection continues from snapshot; connectivity sensor off.
- Snapshot older than the files (backup restore): unverified renders
  excluded; repair issue lists them.
- Render failure: previous render stays; clip shows ffmpeg tail.
- Disk low: renders refused, banner.
- No playable clip: `ServiceValidationError` (script's existing
  "colección sin clip reproducible" path).

## Testing

- App: pytest with real ffmpeg on lavfi fixtures — publication atomicity,
  never-reused names, crash recovery (staging, unrecognized, missing), GC
  fence (held sets, pins + merge, grace, halts, lock ordering with a second
  process), timing invariants on rendered fixtures with margins,
  fades, loudnorm (±1 LU), crop/trim, legacy import (hard links, id
  preservation), chunked upload, auth, ETag.
- Integration: pytest-homeassistant-custom-component — offline snapshot,
  file verification exclusion, consumer-file writes (merge, lock timeout →
  `not_ready`, adoption before selectable), selection modes (random rounds, sequential,
  custom), activation resets (calendar, override, missed transition across
  restart, per-call season no reset), fallback, dry run, legacy history
  import, response contract (schema test against a JSON Schema shared with
  the App contract tests).
- Contract: shared season fixture table + response JSON Schema +
  OpenAPI validation.
- UI: vitest (time math, i18n completeness, chunking).
- `scripts/verify.sh` (ruff, pyright, pytest, UI tests/build, Docker build).

## Production migration (performed by Claude via HA MCP, consensus with Sol)

Pre-flight: full HA backup (`ha_manage_backup snapshot create`), no cinema
session active (`input_select.cinema_fase == reposo`,
`script.cinema_reproducir` off), outside evening hours, old Worker idle.

1. Add App repo, install, start; add HACS repo, download integration,
   config check, restart HA; confirm the discovery entry and connectivity.
2. `cinema_studio.import_legacy`; verify report: every ready Worker clip
   imported with its id, `r1` linked, timing equal to Worker values.
3. Parity by manifest, not by random picks: for every clip id compare the
   new catalog render timing/duration/name with the old Worker values and
   with `shell_command.cinema_clip_metadata` for a sample (≥ 5 clips per
   collection, including the 1 stale clip). Compare collection order/mode.
   Ordered collections: `dry_run` of new vs old must return the same clip id.
4. `script.cinema_studio_selftest`: a copy of the **entire replacement
   block** (new selection, validation, variable mapping, and fallback) that
   stops before any device step and returns the resulting variables as a
   script response (writes no helpers, never calls
   `script.cinema_registrar`). Both services are called with `dry_run: true`.
   Run it three ways: normal, forced new-path failure (`forzar_respaldo: true` variable
   → fallback path), and invalid contract (`forzar_contrato_invalido`).
   All three must produce valid variables.
5. Rollback copy: `script.cinema_reproducir_v1_backup` (exact copy, never
   called) + MCP edit backup. Edit `script.cinema_reproducir` in place:
   - `seleccion` initialized to `{}`; the selftest-proven block replaces
     only the old selection + metadata steps, at the same position (before
     any device action).
   - New path: `cinema_studio.select_next_clip` (`continue_on_error: true`,
     `response_variable`), then a full validation (`contract_version == 1`,
     `timing_verified`, `file_verified`, clip id/URI non-empty, URI contains
     clip id, finite timing within invariants). Valid → map
     `duracion/content_start/content_end/lead_in/tail_out/clip_nombre`
     from the response.
   - Invalid or error → the old `cinema_collections.select_next_clip` +
     `shell_command.cinema_clip_metadata` steps verbatim (fallback), logged
     via `script.cinema_registrar` evento `respaldo_seleccion`.
   - Fallback can only happen in this block; nothing after the first
     device action changes. Every other step is diffed equal to the backup.
6. During observation, keep enabled: old App, old integration,
   `automation.pre_compile_cinema_clips`, and
   `automation.cinema_clips_reiniciar_historial_al_cambiar_de_temporada`
   (the fallback path keeps its own correct history). The new integration's
   `season_entity` = `sensor.temporada_de_cine_activa`.
   Known trade-off: the two histories are independent, so a session that
   falls back may repeat a clip already shown through Studio (rare; only
   on fallback). The App needs no nightly compile: it renders on every
   recipe change; the old 03:00 automation only keeps the fallback Worker
   current and is disabled by the user at the exit gate.
7. Refresh history at cut-over (`import_legacy history_only`) immediately
   before step 5 so the new path continues where the old one stopped.

Observation exit gate (user decides; documented in `docs/ROLLBACK.md`):
≥ 20 sessions and ≥ 7 days with `resultado == completado` rates no worse
than the previous 7 days and zero `respaldo_seleccion` events. After that,
the user may: switch to native seasons (clear `season_entity`), disable the
old reset and 03:00 compile automations, remove the fallback block, then
uninstall the old product.

Rollback at any time: restore `script.cinema_reproducir` from
`_v1_backup` (one MCP call or paste in the UI). Nothing else needs undoing;
the old product was never stopped.

## Release

Integration tags `vX.Y.Z` (HACS), App version in `app/config.yaml`. First
release `v0.1.0` (pre-1.0 until the user approves after observation).
