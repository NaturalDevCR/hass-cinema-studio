# Cinema Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Home Assistant Supervisor App ("Cinema Studio") and a HACS integration (`cinema_studio`) that import, edit, render, organize and select cinema clips offline-safely, per `docs/superpowers/specs/2026-10-05-cinema-studio-design.md`.

**Architecture:** The App (FastAPI + SQLite + ffmpeg + Vue SPA via Ingress) owns originals, recipes, processing profiles, immutable renders under `/media/cinema-studio/renders/`, collections, seasons and GC. The integration persists the catalog snapshot, verifies files with `stat`, coordinates with GC through a `flock` fence + consumer file on the shared `/media`, resolves seasons, keeps played-set history ported from `cinema_collections`, and answers `cinema_studio.select_next_clip` without contacting the App. Automations keep playback.

**Tech Stack:** Python 3.13, FastAPI, uvicorn, httpx, pydantic v2, sqlite3, ffmpeg/ffprobe; Home Assistant custom integration (aiohttp, DataUpdateCoordinator, Store, fcntl); Vue 3 + TypeScript + Vite + Tailwind 4 + @mdi/js; pytest, pytest-homeassistant-custom-component, vitest; uv; GitHub Actions.

**Reference sources (read them; port, do not reinvent):**
- `~/Dev/hass-sound-effects` — repo layout, tooling, App skeleton (auth, supervisor, discovery, notifier, uploads, app factory, packaging), integration skeleton (client, config flow, coordinator, snapshot, entities, diagnostics), whole UI system.
- `~/Dev/hass-clips-manager/app/src/cinema_collections_worker` — `profile_validation.py`, `ffmpeg.py`, `probe.py`, `jobs.py` (compile + timing), `output_duration.py`.
- `~/Dev/hass-clips-manager/custom_components/cinema_collections` — `history.py` (played-set history), `selection.py` (mode ordering, `_sequential_key`), `api_client.py` (legacy Worker client), `const.py`.

## Global Constraints

- Repository: `NaturalDevCR/hass-cinema-studio`, public, Apache-2.0, default branch `main`.
- Python `>=3.13`; ruff line length 100, `target-version = "py313"`, rules `E,F,I,UP,B,SIM`; pyright `strict` for `app/src/cinema_studio` and `custom_components/cinema_studio`.
- App slug `cinema_studio`; Ingress port `8099`; base image `ghcr.io/home-assistant/{arch}-base-python:3.13-alpine3.22`; arch `aarch64`, `amd64`; built locally by the Supervisor (no `image:` key); `map: [media:rw]`; `homeassistant_api: true`, `hassio_api: true`, `discovery: [cinema_studio]`.
- Integration domain `cinema_studio`; single instance enforced in the config flow (no manifest `single_config_entry`); `iot_class: local_polling`; `integration_type: service`; HA minimum `2025.12.0` in `hacs.json`.
- Media root inside both containers: `/media`. App root `/media/cinema-studio/` with `originals/`, `renders/`, `assets/`, `consumers/`, `.work/`, `.gc.lock`. Render file name `<clip_id>-r<n>-<render_uuid>.mp4` (`render_uuid` = `uuid4().hex`). Media URI `media-source://media_source/local/cinema-studio/renders/<clip_id>/<file>`.
- Ingress peer `172.30.32.2`; dev bypass env `CINEMA_STUDIO_DEV=1`. Token `/data/api_token`; instance id `/data/instance_id`; DB `/data/studio.db`; thumbnails `/data/thumbs/`.
- Built-in season `regular` (no range, cannot be deleted, plays collection `regular`). Built-in normalization profiles `standard` (−16, −1.5, 11), `loud` (−13, −1.0, 11), `soft` (−20, −1.5, 11), `voice` (−18, −1.5, 7). Seed collection `regular` "Regular" mode `random`. Seed processing profile = Clips `ProcessingProfile()` defaults with id `compatibility-4k-loudness`.
- Timing: seconds, rounded once at publish to 3 decimals; invariants (tolerance 0.001): `0 < duration <= 7200`, `content_start == lead_in`, `0 <= content_start < content_end <= duration`, `|content_duration-(content_end-content_start)| <= 0.001`, `|tail_out-(duration-content_end)| <= 0.001`; all finite.
- GC: retired/unrecognized render deleted only if absent from every consumer's `held_render_ids`, unpinned (pin `expires_at` + 10 min), age ≥ 48 h, under exclusive `flock` of `.gc.lock`; halts on missing/unparseable consumer file or network filesystem. Pins last 6 h.
- Response `contract_version: 1`. Error translation keys: `not_ready`, `no_playable_clip`, `unknown_collection`, `unknown_season`.
- UI: relative URLs, hash router, es + en, dark theme, accent amber `#f59e0b`, mobile-first (bottom tabs < `md`, sidebar ≥ `md`).
- Test-on-device never targets entities in `protected_entities` (default `["media_player.otocuma_dp", "cover.ocl_screen_projector"]`) nor any `remote.*`, `cover.*`, `switch.*`, `light.*` entity; only `media_player.*` allowed.
- Commits: Conventional Commits; every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Stage only files the task touched (`git add <paths>`), never `git add -A`.

---

## File Structure

```
.github/workflows/quality.yml       verify.sh (ruff, pyright, pytest, vitest, UI build)
.github/workflows/validate.yml      hassfest + HACS action
.github/workflows/app-build.yml     docker buildx app/ amd64 + aarch64 (no push)
pyproject.toml uv.lock .gitignore LICENSE README.md hacs.json repository.yaml
scripts/verify.sh
contract/openapi-v1.yaml            v1 endpoints
contract/season_cases.json          shared calendar fixtures
contract/selection_response.schema.json   JSON Schema of select_next_clip response
contract/timing_cases.json          shared timing-invariant fixtures (App + integration)

app/config.yaml app/Dockerfile app/DOCS.md app/CHANGELOG.md app/icon.png app/logo.png
app/translations/{en,es}.yaml  app/rootfs/usr/bin/cinema-studio
app/src/cinema_studio/
  __init__.py        __version__
  config.py          Paths, load_options()
  errors.py          StudioError, NotFoundError, ConflictError, InvalidError
  models.py          pydantic models (API + DB)
  seasons.py         season_matches(), resolve_calendar_season()  (copy of SE)
  timing.py          Timing, round_timing(), timing_problems() (Task 1; identical copy in the integration)
  timing_validation.py validate_timing() → InvalidError
  db.py              Database (schema, migrations, seeds)
  repository.py      Repository (CRUD, renders, catalog revision, catalog document)
  profiles.py        ProcessingProfile & co (port of Clips profile_validation.py)
  probe.py           ffprobe wrapper (port of Clips probe.py)
  ffmpeg.py          FfmpegCommandBuilder (port of Clips ffmpeg.py + recipe: trim, crop, fades, gain, loudness override, margins)
  media.py           measure_loudness, thumbnails/filmstrip, sha256 fingerprint
  render.py          RenderEngine.compile(): run ffmpeg, validate output, compute timing
  storage.py         MediaStore (layout, exclusive publish, staging, recovery, disk estimate)
  fence.py           GcFence (flock, consumer files), Gc (rules)
  jobs.py            JobQueue (import-probe, render, preview, thumbnails, gc)
  notifier.py        CatalogNotifier (copy of SE)
  legacy.py          LegacyImporter (staged import of Worker manifest)
  uploads.py         UploadStore (copy of SE, video extensions)
  supervisor.py      SupervisorClient (copy of SE)
  auth.py            TokenStore, require_ingress, require_bearer (copy of SE)
  api_v1.py          /api/v1 router
  api_ui_organize.py collections, seasons, profiles, assets, settings, state, token
  api_ui_clips.py    clips, uploads, recipe, preview, streams, thumbs, test-on-device, jobs
  app.py  main.py
app/ui/                              Vue SPA (Track C)

custom_components/cinema_studio/
  __init__.py manifest.json const.py api.py catalog.py timing.py seasons.py history.py
  activation.py fence.py verify.py coordinator.py manager.py legacy.py services.py services.yaml
  config_flow.py entity.py sensor.py select.py binary_sensor.py diagnostics.py icons.json
  translations/{en,es}.json brand/icon.png

tests/studio/  tests/integration/  tests/contract/  tests/test_repository_metadata.py
docs/ROLLBACK.md  docs/migration.md
```

Tracks after Task 1 run in parallel in separate git worktrees:
- **Track A (App backend):** Tasks 2–10, branch `track/studio`.
- **Track B (Integration):** Tasks 11–16, branch `track/integration`.
- **Track C (UI):** Tasks 17–21, branch `track/ui` (consumes the Shared API Reference only; mock server in tests).
- **Final:** Task 22 (merge, e2e, docs, publish, release) on `main`; Task 23 (production migration) operational.

Model assignment (user preference): **Sol** = `codex exec -m gpt-6.1-sol` for hard tasks; **Luna** = `codex exec -m gpt-6-luna` or **Sonnet** subagents for focused tasks.

---

## Shared API Reference (binding for all tracks)

JSON snake_case. Timestamps ISO-8601 UTC with `Z`. Errors `{"detail": "<message>"}` with 400/401/403/404/409/413/415/422/503.

### Types

```ts
type Season = { id: string; name: string; color: string; icon: string;
  start: string | null; end: string | null;      // "MM-DD" inclusive; null only for regular
  priority: number; collection_id: string; builtin: boolean }
type Collection = { id: string; name: string; color: string; icon: string;
  playback_mode: "random" | "sequential" | "custom"; order: string[];
  processing_profile_id: string; enabled: boolean; sort_order: number }
type NormalizationProfile = { id: string; name: string; target_lufs: number; true_peak: number; lra: number }
type ProcessingProfile = { id: string; name: string; settings: ProcessingProfileSettings }
  // settings = Clips ProcessingProfile.model_dump(mode="json") verbatim
type Asset = { filename: string; size: number | null; status: "ready" | "missing" }
type Crop = { x: number; y: number; w: number; h: number }      // source pixels
type Recipe = { trim_start: number; trim_end: number | null; crop: Crop | null;
  fade_in: number | null; fade_out: number | null;               // null = processing profile fades
  gain_db: number; profile_id: string | null;                    // normalization override
  lead_in: number; tail_out: number }                            // margins (default 2.0 / 2.0)
type OriginalInfo = { filename: string; size: number; sha256: string; duration: number;
  width: number; height: number; fps: number | null; has_audio: boolean; video_codec: string }
type Render = { id: string; n: number; relative_path: string; media_path: string; size: number; sha256: string;
  duration: number; content_start: number; content_end: number; lead_in: number; tail_out: number;
  content_duration: number; timing_source: "measured" | "legacy_worker" | "legacy_full_file";
  integrated_lufs: number | null; true_peak: number | null; recipe_hash: string;
  profile_fingerprint: string; published_at: string }
  // relative_path = "cinema-studio/renders/<clip_id>/<file>" (relative to /media);
  // media_path identical (kept separate for future roots)
type ClipStatus = "processing" | "ready" | "rendering" | "failed"
type Clip = { id: string; collection_id: string; title: string; source_name: string; enabled: boolean;
  notes: string; original: OriginalInfo | null; recipe: Recipe; render: Render | null;
  render_pending: boolean; status: ClipStatus; error: string | null; needs_source: boolean;
  sort_key: string; selection_count: number; last_selected_at: string | null;
  has_preview: boolean; has_thumbs: boolean; created_at: string; updated_at: string }
type Job = { id: string; kind: "probe" | "render" | "preview" | "thumbs" | "legacy_import";
  clip_id: string | null; clip_title: string; status: "queued" | "running" | "done" | "failed";
  progress: number; error: string | null; created_at: string; started_at: string | null; finished_at: string | null }
type TestTarget = { id: string; label: string; entity_id: string }   // media_player.* only
type Settings = { max_upload_mb: number; max_duration_s: number; default_lead_in: number;
  default_tail_out: number; disk_reserve_bytes: number; test_targets: TestTarget[];
  protected_entities: string[] }
type ConsumerInfo = { consumer_id: string; last_seen_at: string | null; held_revision: number | null;
  file_present: boolean; pins: number }
type State = { version: string; api_token_masked: string; catalog_revision: number;
  discovery: { status: "ok" | "failed" | "unavailable"; message: string | null };
  storage: { free_bytes: number; originals_bytes: number; renders_bytes: number;
             retired_bytes: number; work_bytes: number; network_fs: boolean };
  gc: { enabled: boolean; halted_reason: string | null; last_run_at: string | null; deleted_last_run: number };
  consumers: ConsumerInfo[]; legacy_import: LegacyReport | null; settings: Settings }
type LegacyReport = { run_id: string; started_at: string; finished_at: string | null; catalog_revision: number;
  imported: string[]; queued_for_render: string[]; needs_source: string[];
  skipped: { clip_id: string; reason: string }[]; missing_assets: string[] }
```

### Integration API v1 (bearer auth; every request sends `X-Cinema-Consumer: <entry_id>`)

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `api/v1/health` | – | `{status:"ok", version, api_version:1, instance_id}` |
| GET | `api/v1/catalog` | `If-None-Match` | `200 Catalog` + `ETag: "rev-<n>"`, or `304` |
| POST | `api/v1/selections` | `{events:[{selection_id, clip_id, render_id, catalog_revision, selected_at}]}` (max 500) | `204` |
| POST | `api/v1/import/legacy` | `LegacyStageRequest` or `LegacyCommitRequest` | stage → `200 LegacyStageResponse`; commit → `200 LegacyReport` (synchronous; may take minutes; 409 if another run is active) |

```ts
type Catalog = { contract_version: 1; revision: number; instance_id: string; generated_at: string;
  seasons: Omit<Season, "builtin">[];
  collections: Omit<Collection, "sort_order" | "processing_profile_id">[];
  clips: { id: string; collection_id: string; title: string; source_name: string; enabled: boolean;
    sort_key: string; render_pending: boolean; render: Render }[] }   // only clips with render != null
type LegacyManifest = {
  worker: { version: string; queue_depth: number; active_job_ids: string[] };
  roots: { source: string; compiled: string };     // absolute paths as seen in /media
  collections: { id: string; name: string; playback_mode: string; ordered_clip_ids: string[];
                 processing_profile_id: string; enabled: boolean }[];
  profiles: { id: string; name: string; settings: object }[];
  assets: string[];
  seasons: { id: string; name: string; start: string | null; end: string | null; priority: number;
             collection_id: string }[];
  clips: { id: string; collection_id: string; state: string; relative_source_path: string;
           relative_output_path: string | null; output_duration_seconds: number | null;
           output_available: boolean; metadata: Record<string, unknown>; updated_at: string }[] }
type LegacyStageRequest = { phase: "stage"; manifest: LegacyManifest }
type LegacyStageResponse = { run_id: string; staged: string[]; rejected: { clip_id: string; reason: string }[] }
type LegacyCommitRequest = { phase: "commit"; run_id: string; clips: LegacyManifest["clips"] }
```

Legacy import is two calls so the App never needs Worker credentials: (1) `POST api/v1/import/legacy` with `phase: "stage"` + manifest → App stages and verifies, returns `{run_id, staged: [clip_id], rejected: [...]}`; (2) integration re-fetches the Worker clips and calls `POST api/v1/import/legacy` with `{phase: "commit", run_id, clips: <re-fetched clips>}` → App reconciles (`updated_at`, `metadata.output_fingerprint`, `metadata.source_fingerprint` unchanged) and publishes → `LegacyReport`. A run left in stage state > 1 h is discarded (staged files deleted).

### UI API (`api/ui/*`, Ingress auth)

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `state` | – | `State` |
| GET | `token` / POST `token/rotate` | – | `{token}` / `{api_token_masked}` |
| GET / PUT | `settings` | `Settings` | `Settings` |
| GET | `collections` | – | `Collection[]` |
| POST | `collections` | `{id?, name, color?, icon?, playback_mode?, processing_profile_id?}` | `Collection` |
| PATCH | `collections/{id}` | partial (no id) | `Collection` |
| PUT | `collections/{id}/order` | `{clip_ids: string[]}` | `Collection` |
| DELETE | `collections/{id}` | – | `204` (409 when clips or seasons reference it; 400 for `regular`) |
| GET/POST/PATCH/DELETE | `seasons`, `seasons/{id}` | as SE + `collection_id` | `Season` / `204` |
| GET | `seasons/resolve?date=YYYY-MM-DD` | – | `{date, season_id, collection_id}` |
| GET/POST/PATCH/DELETE | `normalization-profiles[/{id}]` | as SE profiles | as SE (PATCH returns `{profile, affected_clip_ids}`) |
| POST | `normalization-profiles/{id}/apply` | `{clip_ids: string[]}` or `{collection_id}` | `{queued: number}` |
| GET/POST/PATCH/DELETE | `processing-profiles[/{id}]` | `{id?, name, settings}` | `ProcessingProfile` (409 delete when used) |
| GET | `assets` | – | `Asset[]` |
| POST | `assets` | multipart `file` | `Asset` |
| DELETE | `assets/{filename}` | – | `204` (409 when a profile references it) |
| GET | `clips` / `clips/{id}` | – | `Clip[]` / `Clip` |
| PATCH | `clips/{id}` | `{title?, collection_id?, enabled?, notes?}` | `Clip` |
| PUT | `clips/{id}/recipe` | `Recipe` | `{clip: Clip, job: Job}` (queues render) |
| POST | `clips/{id}/preview` | `Recipe` | `{job: Job}` (preview render 720p, not published) |
| POST | `clips/{id}/rerender` | – | `{job: Job}` |
| DELETE | `clips/{id}` | – | `204` (render retired, original deleted) |
| POST | `clips/bulk` | `{ids, set:{collection_id?, enabled?, profile_id?}}` | `{updated, queued}` |
| GET | `clips/{id}/original`, `clips/{id}/preview`, `clips/{id}/render` | Range | video bytes |
| GET | `clips/{id}/poster.jpg` | – | JPEG poster of the published render (`thumbs/<clip_id>/r<n>/poster.jpg`), fallback original poster |
| GET | `clips/{id}/filmstrip.json`, `clips/{id}/filmstrip/{index}.jpg` | – | filmstrip of the **original** timeline (`thumbs/<clip_id>/original/`), `{interval, count, width, height}` / JPEG |
| POST | `clips/{id}/source` | `{upload_id}` (a completed-bytes upload session, see uploads) | `Clip` (original replaced, `needs_source` false, sha256 recorded, render queued) |
| POST | `clips/{id}/test` | `{target_id, source: "preview" | "render"}` | `{ok: true, media_content_id}` |
| POST | `uploads` / PUT `uploads/{id}/chunks/{n}` / POST `uploads/{id}/complete` | as SE; complete body `{collection_id, title?}` | `Clip` (for source repair, call `clips/{id}/source` with the upload id instead of `complete`) |
| GET | `jobs` | – | `Job[]` |
| POST | `gc/run` | – | `{deleted: number, halted_reason: string | null}` (`deleted` = `len(GcResult.deleted)`) |

### Home Assistant contract

- Event fired by the App: `cinema_studio_catalog_changed` `{revision}` (debounced 1 s).
- Discovery payload: `{service: "cinema_studio", config: {host, port: 8099, token, instance_id}}`.
- `cinema_studio.select_next_clip` response keys (all always present): `contract_version, instance_id, catalog_revision, selection_id, selected_at, collection_id, season, requested_season, season_source, season_fallback, playback_mode, history_reset, activation_reset, clip_id, title, source_name, render_id, render_n, relative_output_path, media_content_id, media_content_type ("video"), duration_seconds, duration, content_duration, lead_in_duration, tail_out_duration, content_start_offset, content_end_offset, timing_source, timing_verified (true), file_verified (true), render_pending, output_is_stale, size, sha256, profile_fingerprint`. `contract/selection_response.schema.json` is the binding schema.
- Consumer file `/media/cinema-studio/consumers/<entry_id>.json`:
  `{"consumer_id": str, "generation": str, "seq": int, "written_at": iso, "held_revision": int, "held_render_ids": [str], "pins": [{"render_id": str, "expires_at": iso}]}`.
  Lock order: in-process `asyncio.Lock` → exclusive `flock(consumers/<entry_id>.lock)` → shared `flock(.gc.lock)`. App GC: exclusive `flock(.gc.lock)` only.

---
## Task 1: Repository scaffold, tooling, CI, contract

**Model:** Sonnet. **Branch:** `main`.

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `LICENSE`, `README.md` (stub), `hacs.json`, `repository.yaml`, `scripts/verify.sh`, `.github/workflows/{quality,validate,app-build}.yml`, `contract/openapi-v1.yaml`, `contract/season_cases.json`, `contract/timing_cases.json`, `contract/selection_response.schema.json`, `tests/contract/test_openapi.py`, `tests/contract/test_schema.py`, `tests/contract/test_timing_cases.py`, `tests/test_repository_metadata.py`, `app/src/cinema_studio/__init__.py`, `app/src/cinema_studio/timing.py`, `custom_components/cinema_studio/__init__.py` (docstring only), `custom_components/cinema_studio/timing.py`, `custom_components/cinema_studio/manifest.json`, `app/config.yaml`

Both tracks need the timing invariants, so Task 1 ships them (identical code in both packages; a test asserts the two files are byte-identical apart from the module docstring line).

**Interfaces:**
- Produces: `uv sync --all-groups` env for all tracks; `scripts/verify.sh`; contract files with the formats below.

- [ ] **Step 1: Copy tooling from Sound Effects and rename.** Copy `~/Dev/hass-sound-effects/{pyproject.toml,.gitignore,LICENSE,scripts/verify.sh,.github/workflows/*}` and replace every `sound_effects_studio` → `cinema_studio`, `sound_effects` → `cinema_studio`, `sound-effects-studio` → `cinema-studio`, `hass-sound-effects` → `hass-cinema-studio`, "Sound Effects" → "Cinema Studio". In `pyproject.toml` set `name = "hass-cinema-studio"`, `version = "0.1.0"`, wheel package `app/src/cinema_studio`, add to `dev` group `jsonschema>=4.23`, `studio` group `fastapi>=0.115`, `uvicorn[standard]>=0.32`, `httpx>=0.28`, `pydantic>=2.9`, `python-multipart>=0.0.12`; pytest markers `studio`, `integration`. Keep the `.gitignore` entry for `app/src/cinema_studio/static/`.

- [ ] **Step 2: Metadata files**

`hacs.json`:
```json
{"name": "Cinema Studio", "content_in_root": false, "render_readme": true, "homeassistant": "2025.12.0"}
```
`repository.yaml`:
```yaml
name: Cinema Studio
url: https://github.com/NaturalDevCR/hass-cinema-studio
maintainer: NaturalDevCR
```
`custom_components/cinema_studio/manifest.json`:
```json
{
  "domain": "cinema_studio",
  "name": "Cinema Studio",
  "codeowners": ["@NaturalDevCR"],
  "config_flow": true,
  "dependencies": [],
  "after_dependencies": ["hassio", "media_source"],
  "documentation": "https://github.com/NaturalDevCR/hass-cinema-studio",
  "integration_type": "service",
  "iot_class": "local_polling",
  "issue_tracker": "https://github.com/NaturalDevCR/hass-cinema-studio/issues",
  "requirements": [],
  "version": "0.1.0"
}
```
`app/config.yaml`:
```yaml
name: Cinema Studio
version: 0.1.0
slug: cinema_studio
description: Import, edit, render and organize cinema clips for Home Assistant
url: https://github.com/NaturalDevCR/hass-cinema-studio
arch:
  - aarch64
  - amd64
startup: application
init: false
ingress: true
ingress_port: 8099
panel_icon: mdi:movie-open-play
panel_title: Cinema Studio
homeassistant_api: true
hassio_api: true
discovery:
  - cinema_studio
map:
  - media:rw
options:
  log_level: info
schema:
  log_level: list(debug|info|warning|error)
```
`app/src/cinema_studio/__init__.py`:
```python
"""Cinema Studio: the Supervisor App behind the cinema_studio integration."""

__version__ = "0.1.0"
```

- [ ] **Step 3: `contract/season_cases.json`** — copy `~/Dev/hass-sound-effects/contract/season_cases.json` verbatim and append:
```json
{"name": "production halloween single day", "seasons": [{"id": "halloween", "start": "10-31", "end": "10-31", "priority": 10}, {"id": "christmas", "start": "12-01", "end": "01-06", "priority": 20}], "date": "2026-10-31", "expected": "halloween"},
{"name": "production day before halloween", "seasons": [{"id": "halloween", "start": "10-31", "end": "10-31", "priority": 10}, {"id": "christmas", "start": "12-01", "end": "01-06", "priority": 20}], "date": "2026-10-30", "expected": "regular"}
```

- [ ] **Step 4: `contract/timing_cases.json`** — list of `{name, timing:{duration, content_start, content_end, lead_in, tail_out, content_duration}, valid}`:
```json
[
  {"name": "production titanic", "timing": {"duration": 154.133, "content_start": 2.0, "content_end": 152.125, "lead_in": 2.0, "tail_out": 2.008, "content_duration": 150.125}, "valid": true},
  {"name": "no margins legacy", "timing": {"duration": 30.0, "content_start": 0.0, "content_end": 30.0, "lead_in": 0.0, "tail_out": 0.0, "content_duration": 30.0}, "valid": true},
  {"name": "start not lead", "timing": {"duration": 30.0, "content_start": 1.0, "content_end": 28.0, "lead_in": 2.0, "tail_out": 2.0, "content_duration": 27.0}, "valid": false},
  {"name": "end beyond duration", "timing": {"duration": 30.0, "content_start": 2.0, "content_end": 30.5, "lead_in": 2.0, "tail_out": -0.5, "content_duration": 28.5}, "valid": false},
  {"name": "content duration mismatch", "timing": {"duration": 30.0, "content_start": 2.0, "content_end": 28.0, "lead_in": 2.0, "tail_out": 2.0, "content_duration": 25.0}, "valid": false},
  {"name": "tail mismatch", "timing": {"duration": 30.0, "content_start": 2.0, "content_end": 28.0, "lead_in": 2.0, "tail_out": 1.5, "content_duration": 26.0}, "valid": false},
  {"name": "zero duration", "timing": {"duration": 0.0, "content_start": 0.0, "content_end": 0.0, "lead_in": 0.0, "tail_out": 0.0, "content_duration": 0.0}, "valid": false},
  {"name": "too long", "timing": {"duration": 7200.5, "content_start": 0.0, "content_end": 7200.5, "lead_in": 0.0, "tail_out": 0.0, "content_duration": 7200.5}, "valid": false},
  {"name": "start equals end", "timing": {"duration": 10.0, "content_start": 5.0, "content_end": 5.0, "lead_in": 5.0, "tail_out": 5.0, "content_duration": 0.0}, "valid": false},
  {"name": "tolerance edge ok", "timing": {"duration": 10.0, "content_start": 1.0, "content_end": 9.0, "lead_in": 1.0, "tail_out": 1.001, "content_duration": 7.999}, "valid": true}
]
```

- [ ] **Step 5: `contract/selection_response.schema.json`** — JSON Schema draft 2020-12, `type: object`, `additionalProperties: false`, every key from the Home Assistant contract listed in `required`. Types: strings for ids/uris/timestamps/`season_source`/`timing_source`/`sha256`/`profile_fingerprint`/`playback_mode`/`season`/`requested_season`; `contract_version` `const: 1`; integers `catalog_revision`, `render_n` (min 1), `size` (min 1); booleans `season_fallback`, `history_reset`, `activation_reset`, `render_pending`, `output_is_stale`; `timing_verified` and `file_verified` `const: true`; numbers (finite) for the seven timing fields with `duration`/`duration_seconds` `exclusiveMinimum: 0, maximum: 7200`; `media_content_type` `const: "video"`; `media_content_id` `pattern: "^media-source://media_source/local/cinema-studio/renders/"`; `season_source` enum `["action","override","entity","calendar","default"]`; `timing_source` enum `["measured","legacy_worker","legacy_full_file"]`; `playback_mode` enum `["random","sequential","custom"]`.

- [ ] **Step 6: `contract/openapi-v1.yaml`** — OpenAPI 3.1 with the four v1 paths, `bearerAuth`, header parameter `X-Cinema-Consumer` (required) on every path, and schemas `Health`, `Catalog`, `CatalogSeason`, `CatalogCollection`, `CatalogClip`, `Render`, `SelectionEvent`, `SelectionBatch`, `LegacyManifest`, `LegacyStageRequest`, `LegacyStageResponse`, `LegacyCommitRequest`, `LegacyReport`, `Error` field-for-field with the Shared API Reference (all fields required; nullable typed `["<type>","null"]`).

- [ ] **Step 7: Tests**

```python
# tests/contract/test_openapi.py
from pathlib import Path

import yaml
from openapi_spec_validator import validate

CONTRACT = Path(__file__).resolve().parents[2] / "contract" / "openapi-v1.yaml"


def test_contract_is_valid_openapi() -> None:
    validate(yaml.safe_load(CONTRACT.read_text(encoding="utf-8")))


def test_contract_declares_v1_paths() -> None:
    document = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert set(document["paths"]) == {
        "/api/v1/health", "/api/v1/catalog", "/api/v1/selections", "/api/v1/import/legacy",
    }
```

```python
# tests/contract/test_schema.py
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2] / "contract"
SCHEMA = json.loads((ROOT / "selection_response.schema.json").read_text())

VALID = {
    "contract_version": 1, "instance_id": "abc", "catalog_revision": 3,
    "selection_id": "s1", "selected_at": "2026-10-05T03:30:00Z", "collection_id": "regular",
    "season": "regular", "requested_season": "regular", "season_source": "entity",
    "season_fallback": False, "playback_mode": "random", "history_reset": False,
    "activation_reset": False, "clip_id": "015a9551-1372-4e6c-85e6-288852848fb2",
    "title": "titanic-1", "source_name": "titanic-1.mp4", "render_id": "f" * 32, "render_n": 1,
    "relative_output_path": "cinema-studio/renders/015a9551-1372-4e6c-85e6-288852848fb2/x.mp4",
    "media_content_id": "media-source://media_source/local/cinema-studio/renders/015a9551-1372-4e6c-85e6-288852848fb2/x.mp4",
    "media_content_type": "video", "duration_seconds": 154.133, "duration": 154.133,
    "content_duration": 150.125, "lead_in_duration": 2.0, "tail_out_duration": 2.008,
    "content_start_offset": 2.0, "content_end_offset": 152.125, "timing_source": "legacy_worker",
    "timing_verified": True, "file_verified": True, "render_pending": False,
    "output_is_stale": False, "size": 123, "sha256": "a" * 64, "profile_fingerprint": "p",
}


def test_schema_is_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA)


def test_valid_example_passes() -> None:
    Draft202012Validator(SCHEMA).validate(VALID)


def test_missing_key_fails() -> None:
    broken = dict(VALID)
    del broken["timing_verified"]
    assert list(Draft202012Validator(SCHEMA).iter_errors(broken))


def test_unverified_fails() -> None:
    assert list(Draft202012Validator(SCHEMA).iter_errors({**VALID, "file_verified": False}))
```

`tests/test_repository_metadata.py`: copy from SE and adapt: versions agree across `manifest.json`, `app/config.yaml`, `__init__.__version__`; hacs name "Cinema Studio"; app slug `cinema_studio`, ingress 8099, `"media:rw" in map`, discovery `["cinema_studio"]`, no `image` key.

- [ ] **Step 7b: Timing module** — write `app/src/cinema_studio/timing.py` and copy it to `custom_components/cinema_studio/timing.py`:

```python
"""Timing invariants shared by the Cinema Studio App and integration (kept identical in both)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

TOLERANCE = 0.001
MAX_DURATION = 7200.0


@dataclass(frozen=True)
class Timing:
    duration: float
    content_start: float
    content_end: float
    lead_in: float
    tail_out: float
    content_duration: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def round_timing(timing: Timing) -> Timing:
    return Timing(**{key: round(value, 3) for key, value in asdict(timing).items()})


def timing_problems(timing: Timing) -> list[str]:
    values = asdict(timing)
    problems = [f"{key} is not finite" for key, value in values.items() if not math.isfinite(value)]
    if problems:
        return problems
    if not 0 < timing.duration <= MAX_DURATION:
        problems.append("duration out of range")
    if abs(timing.content_start - timing.lead_in) > TOLERANCE:
        problems.append("content_start differs from lead_in")
    if not 0 <= timing.content_start < timing.content_end <= timing.duration + TOLERANCE:
        problems.append("content bounds out of order")
    if abs(timing.content_duration - (timing.content_end - timing.content_start)) > TOLERANCE:
        problems.append("content_duration mismatch")
    if abs(timing.tail_out - (timing.duration - timing.content_end)) > TOLERANCE:
        problems.append("tail_out mismatch")
    if timing.lead_in < 0 or timing.tail_out < -TOLERANCE:
        problems.append("negative margin")
    return problems
```

`tests/contract/test_timing_cases.py`: parametrize over `contract/timing_cases.json` for **both** `cinema_studio.timing` (App, import via `app/src` path) and `custom_components.cinema_studio.timing`, asserting `(timing_problems(Timing(**case["timing"])) == []) == case["valid"]`; plus `test_timing_modules_identical` comparing both files with the first line removed.

- [ ] **Step 8: Verify** — `uv sync --all-groups && uv run pytest -q tests/contract tests/test_repository_metadata.py && uv run ruff check . && uv run ruff format --check .` → PASS.
- [ ] **Step 9: README stub** (title, one paragraph, "Work in progress").
- [ ] **Step 10: Commit** `chore: scaffold repository, tooling, CI and v1 contract`.

---

# Track A — Cinema Studio App backend

Tests in `tests/studio/`, `pytestmark = pytest.mark.studio`, real `ffmpeg`/`ffprobe`. Shared fixtures `tests/studio/conftest.py`:

```python
"""Fixtures for Cinema Studio tests."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from cinema_studio.config import Paths


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    p = Paths(
        data_dir=tmp_path / "data",
        media_dir=tmp_path / "media",
        static_dir=tmp_path / "static",
        dev_mode=False,
    )
    p.data_dir.mkdir(parents=True)
    p.media_dir.mkdir(parents=True)
    return p


@pytest.fixture
def make_video(tmp_path: Path) -> Callable[..., Path]:
    """Generate a small test video (testsrc + sine) with ffmpeg."""

    def _make(
        name: str = "clip.mp4",
        seconds: float = 4.0,
        width: int = 320,
        height: int = 180,
        fps: int = 24,
        audio: bool = True,
        volume_db: float = -20.0,
    ) -> Path:
        out = tmp_path / "fixtures" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}:duration={seconds}",
        ]
        if audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate=48000",
                    "-af", f"volume={volume_db}dB"]
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
        if audio:
            cmd += ["-c:a", "aac", "-shortest"]
        cmd.append(str(out))
        subprocess.run(cmd, check=True)
        return out

    return _make


@pytest.fixture
def small_profile_settings() -> dict[str, object]:
    """A fast ProcessingProfile for tests: 320x180@24, ultrafast, loudness two-pass -18."""
    return {
        "video": {"width": 320, "height": 180, "fps": 24, "preset": "ultrafast",
                  "scaling": {"strategy": "aspect_fit", "width": 320, "height": 180}},
        "loudness": {"mode": "two_pass", "integrated_lufs": -18, "true_peak_dbtp": -1.5, "lra_lu": 11},
    }
```

## Task 2: Core — config, errors, models, seasons, timing, database, repository

**Model:** Sonnet. **Branch:** `track/studio`.

**Files:** Create `app/src/cinema_studio/{config,errors,models,seasons,db,repository}.py`; Modify `app/src/cinema_studio/timing.py` only to add `validate_timing` **in a new module** `app/src/cinema_studio/timing_validation.py` (keep `timing.py` identical to the integration copy); Test `tests/studio/conftest.py`, `tests/studio/test_repository.py`, `tests/studio/test_timing_validation.py`, `tests/contract/test_season_cases.py` (studio half).

**Interfaces (Produces):**

```python
# config.py
@dataclass(frozen=True)
class Paths:
    data_dir: Path; media_dir: Path; static_dir: Path; dev_mode: bool
    @property
    def root(self) -> Path: ...            # media_dir / "cinema-studio"
    @property
    def originals_dir(self) -> Path: ...   # root / "originals"
    @property
    def renders_dir(self) -> Path: ...     # root / "renders"
    @property
    def assets_dir(self) -> Path: ...      # root / "assets"
    @property
    def consumers_dir(self) -> Path: ...   # root / "consumers"
    @property
    def work_dir(self) -> Path: ...        # root / ".work"
    @property
    def gc_lock_path(self) -> Path: ...    # root / ".gc.lock"
    @property
    def thumbs_dir(self) -> Path: ...      # data_dir / "thumbs"
    @property
    def uploads_dir(self) -> Path: ...     # data_dir / "uploads"
    @property
    def database_path(self) -> Path: ...   # data_dir / "studio.db"
    @classmethod
    def from_env(cls) -> Paths: ...        # /data, /media; env CINEMA_STUDIO_DATA, CINEMA_STUDIO_MEDIA, CINEMA_STUDIO_DEV
def load_options(path: Path) -> dict[str, object]

# errors.py — StudioError, NotFoundError, ConflictError, InvalidError (as SE)

# timing.py — from Task 1 (Timing, round_timing, timing_problems, TOLERANCE, MAX_DURATION); do not edit
# timing_validation.py
def validate_timing(t: Timing) -> Timing               # round_timing then raise InvalidError("; ".join(problems)) if any

# seasons.py — verbatim copy of ~/Dev/hass-sound-effects/app/src/sound_effects_studio/seasons.py

# models.py — pydantic v2 models for every type in the Shared API Reference plus inputs:
#   SeasonCreate/Update (collection_id), CollectionCreate/Update, NormalizationProfileCreate/Update,
#   ProcessingProfileRecord(id, name, settings: dict), ClipUpdate, BulkSet, Settings, TestTarget,
#   SelectionEvent/SelectionBatch(max 500), Job, Recipe(validate_for(original: OriginalInfo) -> None),
#   RenderRecord (Render + clip_id, state, retired_at, retired_revision, created_at)
#   slugify(), utcnow_iso() as SE.
RenderState = Literal["published", "retired", "unrecognized", "missing", "deleted"]

# db.py — Database(path) as SE, schema below, PRAGMA user_version = 1
# repository.py
class Repository:
    def __init__(self, db: Database, on_catalog_change: Callable[[int], None] | None = None) -> None
    # seasons / collections / normalization profiles / processing profiles / assets: list/get/create/update/delete
    def set_collection_order(self, collection_id: str, clip_ids: list[str]) -> Collection
    # clips
    def list_clips(self) -> list[Clip]; def get_clip(self, clip_id: str) -> Clip
    def create_clip(self, *, clip_id: str | None, collection_id: str, title: str, source_name: str,
                    recipe: Recipe, original: OriginalInfo | None, sort_key: str,
                    needs_source: bool = False, status: ClipStatus = "processing") -> Clip
    def update_clip(self, clip_id: str, data: ClipUpdate) -> Clip
    def set_recipe(self, clip_id: str, recipe: Recipe) -> Clip         # sets render_pending=True
    def set_original(self, clip_id: str, original: OriginalInfo) -> Clip
    def set_status(self, clip_id: str, status: ClipStatus, error: str | None = None) -> Clip
    def set_flags(self, clip_id: str, *, has_preview: bool | None = None, has_thumbs: bool | None = None,
                  render_pending: bool | None = None, needs_source: bool | None = None) -> None
    def delete_clip(self, clip_id: str) -> None                         # retires its published render
    def bulk_update(self, ids: list[str], data: BulkSet) -> int
    def record_selections(self, events: list[SelectionEvent]) -> None
    # renders
    def next_render_n(self, clip_id: str) -> int                        # max(n)+1 over all rows (incl. deleted)
    def publish_render(self, render: RenderRecord) -> Clip              # one transaction: insert, point clip,
                                                                        # retire previous (retired_revision=new rev), bump revision,
                                                                        # status ready, render_pending False
    def list_renders(self, *, states: set[RenderState] | None = None) -> list[RenderRecord]
    def get_render(self, render_id: str) -> RenderRecord
    def add_unrecognized_render(self, *, render_id: str, clip_id: str, relative_path: str, size: int,
                                mtime_iso: str) -> None
    def mark_render(self, render_id: str, state: RenderState) -> None   # missing/deleted; if a published render
                                                                        # becomes missing → clip falls back to newest
                                                                        # earlier render with state published|retired whose
                                                                        # file exists (caller passes exists callback), else status failed
    def fallback_after_missing(self, clip_id: str, exists: Callable[[str], bool]) -> Clip
    # consumers seen via HTTP (stats/System only)
    def touch_consumer(self, consumer_id: str, held_revision: int | None) -> None
    def list_consumers_seen(self, since_days: int = 30) -> list[tuple[str, str]]   # (id, last_seen_at)
    # settings & catalog
    def get_settings(self) -> Settings; def update_settings(self, data: Settings) -> Settings
    def catalog_revision(self) -> int
    def catalog_document(self, instance_id: str) -> dict[str, object]   # Catalog shape exactly
    # legacy runs
    def save_legacy_report(self, report: LegacyReport) -> None; def last_legacy_report(self) -> LegacyReport | None
```

Schema:

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL, icon TEXT NOT NULL,
  playback_mode TEXT NOT NULL, ord TEXT NOT NULL DEFAULT '[]', processing_profile_id TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0);
CREATE TABLE seasons (id TEXT PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL, icon TEXT NOT NULL,
  start TEXT, "end" TEXT, priority INTEGER NOT NULL DEFAULT 0, collection_id TEXT NOT NULL REFERENCES collections(id),
  builtin INTEGER NOT NULL DEFAULT 0);
CREATE TABLE normalization_profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL, target_lufs REAL NOT NULL,
  true_peak REAL NOT NULL, lra REAL NOT NULL);
CREATE TABLE processing_profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL, settings TEXT NOT NULL);
CREATE TABLE assets (filename TEXT PRIMARY KEY, size INTEGER, status TEXT NOT NULL);
CREATE TABLE clips (id TEXT PRIMARY KEY, collection_id TEXT NOT NULL REFERENCES collections(id),
  title TEXT NOT NULL, source_name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, notes TEXT NOT NULL DEFAULT '',
  original TEXT, recipe TEXT NOT NULL, published_render_id TEXT, render_pending INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL, error TEXT, needs_source INTEGER NOT NULL DEFAULT 0, sort_key TEXT NOT NULL,
  selection_count INTEGER NOT NULL DEFAULT 0, last_selected_at TEXT, has_preview INTEGER NOT NULL DEFAULT 0,
  has_thumbs INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE renders (id TEXT PRIMARY KEY, clip_id TEXT NOT NULL, n INTEGER NOT NULL, relative_path TEXT NOT NULL UNIQUE,
  size INTEGER NOT NULL, sha256 TEXT NOT NULL, duration REAL NOT NULL, content_start REAL NOT NULL,
  content_end REAL NOT NULL, lead_in REAL NOT NULL, tail_out REAL NOT NULL, content_duration REAL NOT NULL,
  timing_source TEXT NOT NULL, integrated_lufs REAL, true_peak REAL, recipe_hash TEXT NOT NULL,
  profile_fingerprint TEXT NOT NULL, state TEXT NOT NULL, published_at TEXT, retired_at TEXT,
  retired_revision INTEGER, created_at TEXT NOT NULL);
CREATE INDEX renders_clip ON renders(clip_id, n);
CREATE TABLE consumers_seen (consumer_id TEXT PRIMARY KEY, last_seen_at TEXT NOT NULL, held_revision INTEGER);
CREATE TABLE legacy_reports (run_id TEXT PRIMARY KEY, report TEXT NOT NULL, created_at TEXT NOT NULL);
```

Rules (raise the listed error):
- Seasons as SE plus `collection_id` must exist → `InvalidError`; regular: only name/color/icon/collection_id updatable; delete regular → `InvalidError`.
- Collection delete with clips or referenced by a season → `ConflictError`; delete `regular` → `InvalidError`; `playback_mode` enum; `order` entries filtered to existing clip ids of that collection on write.
- Processing profile `settings` validated with `profiles.ProcessingProfile.model_validate` (Task 3 provides `profiles.py`; until then Task 2 stores dict and Task 3 adds validation call — implement Task 2 with a `validate_settings: Callable[[dict], dict] = lambda s: s` constructor hook, default identity; Task 3's app factory passes the real validator). Delete when used by a collection → `ConflictError`.
- Normalization profile delete when a clip recipe uses it → `ConflictError`.
- Every write that changes the catalog document (seasons, collections incl. order, clips metadata/enabled/collection, `publish_render`, `delete_clip`, `bulk_update`) bumps `catalog_revision` in the same transaction and calls `on_catalog_change(rev)` after commit. `set_recipe` bumps (sets `render_pending`). `record_selections`, settings, profile edits, status `processing|rendering`, flags `has_preview/has_thumbs` do not bump.
- `publish_render` requires `validate_timing` to pass on the record's timing (InvalidError otherwise).
- `catalog_document()` includes only clips with `published_render_id` whose render state is `published`; `collections[].order` filtered.
- Seeds: collection `regular` ("Regular", color `#f59e0b`, icon `mdi:movie-open`, mode `random`, profile `compatibility-4k-loudness`), processing profile `compatibility-4k-loudness` (name "Compatibility 4K Loudness", settings `{}` until Task 3 fills defaults through the validator), season `regular` (builtin, collection `regular`), four normalization profiles, settings defaults `{max_upload_mb: 4096, max_duration_s: 7200, default_lead_in: 2.0, default_tail_out: 2.0, disk_reserve_bytes: 2147483648, test_targets: [], protected_entities: ["media_player.otocuma_dp", "cover.ocl_screen_projector"]}`, `meta.catalog_revision = 0`.
- Clip ids: `str(uuid.uuid4())` unless given (import keeps Worker ids). New clip `sort_key` = `f"{collection_id}/{clip_id}.mp4".casefold()` (same rule as the Worker's `_sequential_key`, so sequential order is consistent between imported and new clips).

- [ ] **Step 1: Failing tests** — `test_timing_validation.py` (rounding `1.00049` → `1.0` before checks; `validate_timing` raises InvalidError listing every problem; valid production example returns rounded Timing); `tests/contract/test_season_cases.py` studio half (copy SE file, import `cinema_studio.seasons`); `test_repository.py`: seeds; revision bump/no-bump table above (one assertion each); collection delete conflicts; season with unknown collection → InvalidError; `set_collection_order` filters unknown ids; `publish_render` retires previous with `retired_revision` == new revision and sets clip ready; `publish_render` with invalid timing → InvalidError and nothing changes; `next_render_n` counts deleted rows; `catalog_document` excludes clips without published render and matches the Catalog key set exactly; `fallback_after_missing` picks the newest earlier render whose file exists, else marks failed; `delete_clip` retires the published render.
- [ ] **Step 2: Run** `uv run pytest tests/studio tests/contract -q` → FAIL (modules missing).
- [ ] **Step 3: Implement** the modules.
- [ ] **Step 4: Run** tests + `uv run pyright` + `uv run ruff check . && uv run ruff format --check .` → PASS.
- [ ] **Step 5: Commit** `feat(studio): add models, timing invariants, season calendar, database and repository`.

## Task 3: Media pipeline — profiles, probe, ffmpeg builder, render engine

**Model:** Sol. **Branch:** `track/studio`.

**Files:** Create `app/src/cinema_studio/{profiles,probe,ffmpeg,media,render}.py`; Test `tests/studio/test_profiles.py`, `tests/studio/test_ffmpeg.py`, `tests/studio/test_render.py`, `tests/studio/test_media.py`.

**Interfaces:**
- Consumes: `Recipe`, `NormalizationProfile`, `Timing`, `validate_timing`.
- Produces:

```python
# profiles.py — port of hass-clips-manager profile_validation.py: ProcessingProfile and every sub-model,
#   profile_fingerprint(profile, assets) -> str, validate_profile(...). Asset references resolve against
#   Paths.assets_dir. DEFAULT_PROFILE_ID = "compatibility-4k-loudness".
def validate_settings(settings: Mapping[str, object]) -> dict[str, object]   # model_validate → model_dump(mode="json")

# probe.py — port of Clips probe.py
@dataclass(frozen=True)
class MediaProbe:
    valid: bool; duration: float; video_duration: float | None; audio_duration: float | None
    width: int | None; height: int | None; fps: float | None; has_audio: bool; video_codec: str | None
async def probe(path: Path) -> MediaProbe                     # MediaError when ffprobe fails / no video stream

# media.py
class MediaError(Exception): ...
async def file_sha256(path: Path) -> str                       # streamed, in a thread; hex digest
def legacy_fingerprint(sha256_hex: str, size: int) -> str      # f"{sha256_hex}:{size}" (Worker format)
async def measure_loudness(path: Path, *, start: float | None = None, end: float | None = None) -> tuple[float | None, float | None]
    # (integrated_lufs, true_peak) via loudnorm print_format=json; -inf → None
async def make_poster(src: Path, dst: Path, at: float) -> None              # 640px wide JPEG
async def make_filmstrip(src: Path, dst_dir: Path, *, duration: float) -> dict[str, int | float]
    # always run on the ORIGINAL (editor timeline = source timeline); dst_dir = thumbs/<clip_id>/original/
    # interval = max(1.0, duration / 60) seconds; frames scaled to 160px wide JPEG named 0000.jpg…;
    # writes dst_dir/"filmstrip.json" {"interval", "count", "width", "height"}; returns that dict

# ffmpeg.py — port of Clips FfmpegCommandBuilder + frame_aligned_duration, extended with Recipe:
def frame_aligned_duration(duration_seconds: float, frame_rate: int) -> float      # verbatim
@dataclass(frozen=True)
class RenderPlan:
    source: Path; output: Path; profile: ProcessingProfile; recipe: Recipe
    normalization: NormalizationProfile | None   # overrides profile.loudness targets when set
    intro: Path | None; outro: Path | None; source_duration: float
    preview: bool                                 # preview: 1280x720 (or 640x360 when profile smaller), crf 28, preset veryfast, no loudness two-pass
class FfmpegCommandBuilder:
    def __init__(self, executable: str = "ffmpeg") -> None
    def build(self, plan: RenderPlan, measured: LoudnessStats | None) -> list[str]
# Filter order for the clip branch (all inside the content region):
#   trim (trim_start..trim_end) → crop (recipe.crop, even-aligned) → profile scaling/fps/format (Clips _video_filter)
#   → video fades (recipe.fade_in/out if not None else profile.fade_in_seconds/fade_out_seconds);
#   audio: atrim → loudnorm two-pass (targets from normalization override else profile.loudness) → volume gain_db
#   → afade in/out (same durations) → alimiter at true-peak when gain_db > 0.
#   Then intro/outro concatenation with profile transitions exactly as Clips; then black/silent margins:
#   tpad=start_duration=<lead>:stop_duration=<tail>:color=black and adelay/apad equivalents, with lead/tail
#   = frame_aligned_duration(recipe.lead_in/tail_out, fps) (Clips cast-blackout-margins behavior).
@dataclass(frozen=True)
class LoudnessStats: input_i: float; input_tp: float; input_lra: float; input_thresh: float; target_offset: float

# render.py
@dataclass(frozen=True)
class RenderOutput:
    path: Path; timing: Timing; size: int; sha256: str; integrated_lufs: float | None; true_peak: float | None
    profile_fingerprint: str; recipe_hash: str
class RenderEngine:
    def __init__(self, builder: FfmpegCommandBuilder, *, timeout_for: Callable[[float], float]) -> None
    async def render(self, plan: RenderPlan, on_progress: Callable[[float], None] | None = None) -> RenderOutput
    # 1. two-pass loudness measure (unless preview or loudness disabled) 2. run ffmpeg (no shell, -progress pipe:1)
    # 3. probe output, validate streams like Clips JobRunner._valid_output (dims, fps ±0.05, audio, A/V sync)
    # 4. timing like Clips _compiled_timing_metadata (content_start = lead; content_end = video_duration - tail
    #    if tail > 0 else duration; tail_out = duration - content_end) → validate_timing (rounded)
    # 5. sha256, loudness of final (measure_loudness on content region) → RenderOutput
    # MediaError with stderr tail (last 1000 chars) on any failure; output file removed on failure.
def recipe_hash(recipe: Recipe, normalization: NormalizationProfile | None) -> str   # sha256 of canonical JSON, 16 hex
```

- [ ] **Step 1: Port first, test first.** Copy Clips `profile_validation.py`, `probe.py`, `ffmpeg.py` and the timing/validation parts of `jobs.py` into the new modules, adapting imports; copy their existing tests from `~/Dev/hass-clips-manager/tests/` that cover these modules (grep for `FfmpegCommandBuilder`, `frame_aligned_duration`, `ProcessingProfile`, `_compiled_timing_metadata`) into `tests/studio/` and make them run against the new module paths. Run → FAIL (imports), then green after the copy.
- [ ] **Step 2: Failing tests for the extensions** (`test_ffmpeg.py` string assertions on argv; `test_render.py` real ffmpeg with `small_profile_settings` and `make_video`):
  - recipe trim 1.0→3.0 on a 5 s source with lead/tail 2.0 → output duration ≈ 6.0 ± 0.1; `timing.content_start == 2.0`; `timing.content_end ≈ 4.0 ± 0.05`; first and last 2 s are black (sample frame at 1.0 s and 5.0 s via `ffmpeg -ss … -vframes 1 -f rawvideo` mean luma < 20) and silent (`volumedetect` max_volume < −60 dB on those ranges).
  - crop `{x: 0, y: 0, w: 160, h: 90}` → still 320×180 output (scaled), probe valid.
  - recipe fades null → profile fades used (argv contains `fade=t=in:st=0:d=1`); recipe fade_in 0.5 → `d=0.500`.
  - normalization override `loud` (−13) on a −30 dB source → final integrated loudness within ±1.0 LU of −13; without override → within ±1.0 of the profile −18.
  - intro/outro asset: generate a 1 s intro; profile with intro+outro and 0.5 s transitions → duration ≈ lead + 1 + clip + 1 − transitions + tail (± 0.1) and timing invariants pass.
  - preview mode → 1280x720 not used for a 320x180 profile (keeps 320x180), no two-pass call (spy builder).
  - failure: source is a text file → `MediaError`, output path absent.
  - `recipe_hash` stable across key order; changes when any field changes.
  - `make_filmstrip` on a 10 s clip → `count == 10`, files exist; `make_poster` writes a JPEG (magic `FF D8`).
- [ ] **Step 3: Run** `uv run pytest tests/studio/test_profiles.py tests/studio/test_ffmpeg.py tests/studio/test_render.py tests/studio/test_media.py -q` → FAIL.
- [ ] **Step 4: Implement** with `asyncio.create_subprocess_exec` only.
- [ ] **Step 5: Run** tests + pyright + ruff → PASS.
- [ ] **Step 6: Commit** `feat(studio): port processing profiles and compiler; add recipe edits, margins, previews, thumbnails`.

## Task 4: Media store, publication, recovery, GC fence

**Model:** Sol. **Branch:** `track/studio`.

**Files:** Create `app/src/cinema_studio/{storage,fence}.py`; Test `tests/studio/test_storage.py`, `tests/studio/test_fence.py`.

**Interfaces:**
- Consumes: `Paths`, `Repository`, `RenderOutput`, `Timing`.
- Produces:

```python
# storage.py
RENDER_NAME = re.compile(r"^(?P<clip>[0-9a-f-]{36})-r(?P<n>\d+)-(?P<uuid>[0-9a-f]{32})\.mp4$")
class MediaStore:
    def __init__(self, paths: Paths) -> None
    def ensure_dirs(self) -> None                       # root, originals, renders, assets, consumers, .work (mode 0755)
    def staging_path(self, job_id: str, name: str) -> Path        # .work/<job_id>/<name> (dirs created)
    def publish_file(self, staged: Path, clip_id: str, n: int) -> tuple[str, Path]
        # fsync(staged); render_uuid = uuid4().hex; final = renders/<clip_id>/<clip_id>-r<n>-<uuid>.mp4;
        # os.link(staged, final) (FileExistsError → draw new uuid, max 5 tries); fsync dir; unlink staged.
        # returns (render_uuid, final)
    def relative_path(self, path: Path) -> str          # path relative to media_dir, posix ("cinema-studio/renders/…")
    def store_original(self, src: Path, clip_id: str, filename: str, *, link: bool) -> Path
        # originals/<clip_id>/<safe filename>; link=True → os.link (fallback copy2 on OSError EXDEV), else move
    def clean_work(self) -> None                        # delete everything under .work except "import" runs < 1 h old
    def scan_renders(self) -> list[tuple[str, str, Path, int, float]]  # (render_uuid, clip_id, path, size, mtime)
    def free_bytes(self) -> int
    def is_network_fs(self) -> bool                     # /proc/mounts fstype of media_dir in {nfs, nfs4, cifs, smb3, fuse.sshfs}
    def estimate_render_bytes(self, profile: ProcessingProfile, seconds: float) -> int
        # (maxrate_kbps or bitrate_kbps or 20000) * 1000/8 * seconds * 1.2, plus audio bitrate; ×2 for staging
    def check_space(self, needed: int, reserve: int) -> None   # InvalidError("not enough free space…")
    def storage_usage(self, repo: Repository) -> dict[str, int]

def recover(store: MediaStore, repo: Repository) -> dict[str, int]
    # startup: clean_work(); every file in renders/ matching RENDER_NAME without a DB row → add_unrecognized_render;
    # non-matching files in renders/ are left untouched and logged; every DB render with state published|retired
    # whose file is missing → mark_render(missing) and fallback_after_missing for published ones.
    # clips in status rendering with a published render → ready; without → failed "interrupted".
    # returns counts {"unrecognized", "missing", "interrupted"}

# fence.py
CONSUMER_FILE = "{consumer_id}.json"
@dataclass(frozen=True)
class ConsumerFile:
    consumer_id: str; generation: str; seq: int; written_at: datetime; held_revision: int
    held_render_ids: frozenset[str]; pins: dict[str, datetime]
def parse_consumer_file(data: Mapping[str, Any]) -> ConsumerFile        # ValueError on any malformed field
class GcFence:
    def __init__(self, paths: Paths) -> None
    @contextmanager
    def exclusive(self, timeout: float = 30.0) -> Iterator[None]        # fcntl.flock(LOCK_EX|LOCK_NB) retry loop
    def read_consumers(self) -> tuple[dict[str, ConsumerFile], list[str]]   # (parsed, ids that failed to parse)
@dataclass(frozen=True)
class GcResult:
    deleted: list[str]; halted_reason: str | None
class GarbageCollector:
    def __init__(self, paths: Paths, repo: Repository, fence: GcFence, store: MediaStore,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None
    def run(self) -> GcResult
    # halts (no deletions) when: store.is_network_fs(); any consumer file fails to parse; any consumer seen via HTTP
    # in the last 30 days (repo.list_consumers_seen) has no consumer file.
    # Otherwise under fence.exclusive(): candidates = renders with state retired (age from retired_at) or
    # unrecognized (age from mtime) ≥ 48 h; delete when not in any held_render_ids and no pin with
    # expires_at + 10 min > now; unlink file, mark_render(deleted), remove empty clip dir.
```

- [ ] **Step 1: Failing tests** (`test_storage.py`, `test_fence.py`):
  - `publish_file` produces the exact name pattern, staged path removed, same inode as staged before unlink (check `st_ino` captured before), existing file never overwritten (pre-create a file with the first uuid by monkeypatching `uuid4` → second uuid used).
  - `store_original(link=True)` shares inode with source; source later replaced via `os.replace` leaves ours unchanged (bytes equal original).
  - `recover`: orphan file in renders → `unrecognized` row, file untouched; DB published row with missing file → clip falls back to earlier render / failed; `.work` cleaned except recent import dir.
  - GC: retired 49 h ago, not held, not pinned → deleted; held by a consumer → kept; pinned (expires in future) → kept; pin expired 5 min ago → kept (10 min margin); pin expired 11 min ago → deleted; retired 47 h → kept; unrecognized by mtime 49 h → deleted; unparseable consumer file → halted, nothing deleted; consumer seen via HTTP without file → halted; network fs (monkeypatch `is_network_fs`) → halted.
  - Lock semantics with a second process: spawn `multiprocessing.Process` holding `fcntl.flock(LOCK_SH)` on `.gc.lock` for 1 s; `GcFence.exclusive(timeout=0.2)` raises `TimeoutError`; with timeout 3 succeeds after release.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** tests + pyright + ruff → PASS.
- [ ] **Step 5: Commit** `feat(studio): add immutable media store, crash recovery and flock-fenced GC`.

## Task 5: Job queue and notifier

**Model:** Sonnet. **Branch:** `track/studio`.

**Files:** Create `app/src/cinema_studio/{jobs,notifier}.py`; Test `tests/studio/test_jobs.py`.

**Interfaces:**

```python
# notifier.py — verbatim port of SE notifier.py (CatalogNotifier)
# jobs.py
class JobQueue:
    def __init__(self, repo: Repository, store: MediaStore, engine: RenderEngine, paths: Paths,
                 gc: GarbageCollector) -> None
    async def start(self) -> None; async def stop(self) -> None
    def enqueue_probe(self, clip_id: str) -> Job           # probe original → set_original → enqueue_render + enqueue_thumbs
    def enqueue_render(self, clip_id: str) -> Job          # coalesces a queued (not running) render for the same clip
    def enqueue_preview(self, clip_id: str, recipe: Recipe) -> Job
    def enqueue_thumbs(self, clip_id: str) -> Job
        # original: thumbs/<clip_id>/original/{poster.jpg, filmstrip.json, 0000.jpg…} (once per original sha256)
        # published render: thumbs/<clip_id>/r<n>/poster.jpg (poster at content_start + 1 s)
    def list_jobs(self) -> list[Job]
    async def wait_idle(self, timeout: float = 120) -> None
    async def run_gc(self) -> GcResult                     # runs GarbageCollector.run in a thread
```

Render identity: at enqueue the job freezes `recipe_hash` (Task 3 `recipe_hash`) and the processing-profile fingerprint (profile settings + referenced asset sha256s). On success, `publish_render` stores them; `render_pending` is cleared **only if** the clip's current recipe hash and current profile fingerprint still equal the job's frozen values — otherwise `render_pending` stays true and a new render is enqueued (an older job finishing never hides a newer edit).

Propagation (`JobQueue.propagate(reason)` helpers, called by Task 8/9 endpoints; each sets `render_pending=True` via the repository — which bumps the catalog revision — and enqueues renders):
- `on_processing_profile_changed(profile_id)` → clips in collections using that profile.
- `on_normalization_profile_changed(profile_id)` → clips whose recipe `profile_id` equals it (only when targets changed).
- `on_collection_profile_changed(collection_id)` → clips in that collection.
- `on_asset_changed(filename)` → clips in collections whose profile references the asset as intro or outro (upload of a previously `missing` asset, or replacement).
- moving a clip to a collection with a different processing profile → that clip.

Render job: status `rendering` (or `processing` when no render yet); refuse with failed "needs source" when `needs_source`; resolve collection profile (validate), normalization override, intro/outro assets (missing asset → failed "asset <name> missing: upload it in Organize"); `store.check_space(store.estimate_render_bytes(...), settings.disk_reserve_bytes)`; `engine.render(plan)` into `store.staging_path(job.id, "out.mp4")`; `n = repo.next_render_n`; `store.publish_file`; `repo.publish_render(RenderRecord(...timing_source="measured"...))`; enqueue thumbs. Failure: `set_status(failed, error)` keeps the previous published render; staging removed. Preview job writes `.work/previews/<clip_id>.mp4` via staging + `os.replace`, sets `has_preview`. Hourly background task calls `run_gc()`; job loop never dies (catch `Exception`, error = last 400 chars). One worker, FIFO. Timeout per render = `max(300, 120 * minutes)` (Clips `timeout_seconds_per_minute`).

- [ ] **Step 1: Failing tests** (real ffmpeg, small profile): stale job (recipe changed while rendering — simulate by changing the recipe from the progress callback) publishes but leaves `render_pending` true and enqueues another render; each propagation helper marks exactly the affected clips pending and enqueues them; upload-like flow (create clip with original from `make_video`, `enqueue_probe`) → status ready, render r1 published, file at the recorded path, thumbs present; `set_recipe` + `enqueue_render` → r2 published, r1 retired with file still present; failure (replace original with garbage) → failed, r2 still published; render coalescing; missing asset → failed with message; insufficient space (monkeypatch `free_bytes`) → failed "not enough free space"; preview sets `has_preview` and catalog revision unchanged; notifier debounce (copy SE test).
- [ ] **Step 2–4:** FAIL → implement → PASS (+ pyright, ruff).
- [ ] **Step 5: Commit** `feat(studio): add render job queue, previews, thumbnails and catalog notifier`.

## Task 6: Auth, Supervisor client, v1 API, app factory, main

**Model:** Sonnet. **Branch:** `track/studio`.

**Files:** Create `auth.py`, `supervisor.py` (verbatim ports of SE, renamed), `api_v1.py`, `app.py`, `main.py`; Test `tests/studio/test_auth.py`, `tests/studio/test_supervisor.py` (ported), `tests/studio/test_api_v1.py`.

Rules:
- `create_app(paths, *, supervisor=None, start_background=True) -> FastAPI`; `app.state`: `paths, repo, store, engine, jobs, gc, fence, tokens, supervisor, notifier, instance_id, discovery_status, legacy`.
- Lifespan (when `start_background`): `store.ensure_dirs()`; `recover(store, repo)`; `jobs.start()`; instance id; discovery exactly as SE (service `cinema_studio`, payload `{host, port: 8099, token, instance_id}`); notifier fires `cinema_studio_catalog_changed`; periodic 10 min: `uploads.purge_stale()`; hourly: `jobs.run_gc()`.
- `api_v1.py` (prefix `/api/v1`, `require_bearer`; every route reads `X-Cinema-Consumer` and calls `repo.touch_consumer(consumer_id, held_revision)` where held revision parses from `If-None-Match` `"rev-<n>"`; missing header → 422):
  - `GET /health`, `GET /catalog` (ETag `"rev-<n>"`, 304 on match), `POST /selections` (validate, `record_selections`, 204), `POST /import/legacy` (delegates to `app.state.legacy` from Task 7; until Task 7 lands respond 501).
- Exception mapping and SPA serving as SE (`require_ingress`).

- [ ] **Step 1: Failing tests** — SE auth/supervisor tests ported; v1: no token 401; consumer header missing 422; catalog ETag/304 and `touch_consumer` recorded with held revision; selections update `selection_count`; catalog document validates against `contract/openapi-v1.yaml` `Catalog` schema (load with `jsonschema` from the OpenAPI component).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(studio): add auth, supervisor client, v1 API and app factory`.

## Task 7: Legacy import (App side)

**Model:** Sol. **Branch:** `track/studio`.

**Files:** Create `app/src/cinema_studio/legacy.py`; Modify `api_v1.py` (wire `/import/legacy`), `app.py` (`app.state.legacy`); Test `tests/studio/test_legacy.py`.

**Interfaces:**

```python
class LegacyImporter:
    def __init__(self, paths: Paths, repo: Repository, store: MediaStore, jobs: JobQueue,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None
    async def stage(self, manifest: LegacyManifest) -> LegacyStageResponse
    async def commit(self, run_id: str, clips: list[LegacyClip]) -> LegacyReport
    def discard_stale(self) -> None        # stage runs older than 1 h: delete .work/import/<run_id>
```

Stage (refuse with `ConflictError` if a run is active; `InvalidError` if `worker.queue_depth > 0` or `active_job_ids` non-empty or local time in 03:00–03:30; `InvalidError` unless `roots.source` and `roots.compiled` resolve to directories inside `paths.media_dir` **and** outside `paths.root` — caller-supplied roots are never trusted beyond `/media`, and the App's own tree is never a source):
1. Validate every profile with `profiles.validate_settings` (invalid → rejected `profile_invalid` for its clips).
2. For each clip with `state != "deleted"`:
   - Source: resolve `roots.source / relative_source_path` (must stay inside `roots.source` after `resolve()`; must be a regular file) → `os.link` into `.work/import/<run_id>/src/<clip_id>/<name>` → sha256:size must equal `metadata.source_fingerprint` (else mark `needs_source`; staged source dropped).
   - Output (when `output_available` and `relative_output_path`): resolve under `roots.compiled` → link into `.work/import/<run_id>/out/<clip_id>.mp4` → `legacy_fingerprint(sha256, size) == metadata.output_fingerprint` and `probe(...).duration` within 0.05 s of `output_duration_seconds`; timing from raw `metadata` keys `content_duration_seconds, lead_in_duration_seconds, tail_out_duration_seconds, content_start_offset_seconds, content_end_offset_seconds`: all present & finite → `Timing(duration=output_duration_seconds, …)` must pass `validate_timing` → `timing_source = "legacy_worker"`; all five absent → `legacy_full_file` (start 0, end = duration, margins 0); otherwise (partial/invalid) → output rejected, clip will be `queued_for_render`.
   - Missing fingerprints → that file rejected (never trusted).
3. Persist the stage manifest + per-clip verdicts as JSON in `.work/import/<run_id>/stage.json`; return `{run_id, staged, rejected}`.

Commit:
1. Load stage; for each staged clip compare the re-fetched clip (`updated_at`, `metadata.output_fingerprint`, `metadata.source_fingerprint`) — any difference → skipped `changed_during_import`.
2. Create/update in this order inside a single logical run (each clip in its own DB transaction): processing profiles (same ids; skip existing ids), assets (each referenced filename present in `assets_dir` → ready else row `missing`), collections (same ids; `playback_mode`, `processing_profile_id`; order NOT written yet), seasons from `manifest.seasons` (create or update by id; `regular` updates only `collection_id`), then clips: `store_original(link=True)` from staging; `create_clip(clip_id=<worker id>, title=Path(relative_source_path).stem, source_name=Path(relative_source_path).name, sort_key=relative_output_path.casefold() if relative_output_path else f"{collection}/{id}.mp4".casefold(), recipe=Recipe(lead_in=…, tail_out=… from Worker timing or settings defaults), needs_source=…, status="ready" if output accepted else "processing")`; accepted output → `store.publish_file(staged_out, clip_id, n=1)` + `repo.publish_render(... timing_source ...)`; output rejected but source ok → `jobs.enqueue_render`; clips already present (same id) are skipped `already_imported` (idempotent); a staged clip missing from the re-fetched list is skipped `missing_from_refetch`. After all clips: for each collection **created in this run** call `set_collection_order(ordered_clip_ids)`; existing collections keep their (possibly edited) order. Report `catalog_revision` = revision after the run.
3. Remove `.work/import/<run_id>`; save and return `LegacyReport`.

- [ ] **Step 1: Failing tests** (build a fake Worker tree under `tmp_path/media/cinema-collections/{source,compiled}/regular/…` with `make_video` outputs; compute real fingerprints; use the production example timing scaled to the fixture duration): happy path imports with same ids, inode shared with Worker files, timing equals manifest, `timing_source == "legacy_worker"`; fingerprint mismatch → no render, `queued_for_render`; source mismatch → `needs_source`; all-timing-absent → `legacy_full_file`; partial timing → rejected output; path escape (`../../etc/passwd`) → rejected `unsafe_path`; changed `updated_at` at commit → skipped; staged clip absent from refetch → `missing_from_refetch`; custom order applied after clips exist and preserved on a rerun after the user edits it; roots outside media dir or inside `cinema-studio/` → InvalidError; second run → `already_imported`; busy Worker → InvalidError; run older than 1 h discarded; Worker later `os.replace`s its compiled file → our render bytes unchanged.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(studio): add staged, fingerprint-verified legacy import`.

## Task 8: UI API — organize, settings, state, token, assets, GC

**Model:** Sonnet. **Branch:** `track/studio`.

**Files:** Create `api_ui_organize.py`; Modify `app.py`; Test `tests/studio/test_api_ui_organize.py`.

Endpoints exactly as the UI API rows `state`, `token*`, `settings`, `collections*`, `seasons*`, `normalization-profiles*`, `processing-profiles*`, `assets*`, `gc/run`. Prefix `/api/ui`, `require_ingress`. `state.consumers`: union of `repo.list_consumers_seen()` and consumer files, with `file_present`, `held_revision`, pin count. `state.gc` from the last `GcResult` (kept in `app.state`). `normalization-profiles/{id}/apply` with `{clip_ids}` or `{collection_id}` sets `recipe.profile_id` and enqueues renders. `PUT settings` validates `test_targets` (`media_player.` only, unique ids, not in `protected_entities`). Asset upload: multipart, extension in `.mp4 .mov .mkv .webm .m4v`, saved atomically to `assets_dir/<safe name>`, probed (invalid → 422), status ready, then `jobs.on_asset_changed(name)`; asset delete 409 when referenced by any processing profile (`intro_reference`/`outro_reference`). Processing profile PATCH → `jobs.on_processing_profile_changed`; normalization profile PATCH with changed targets → `jobs.on_normalization_profile_changed`; collection PATCH changing `processing_profile_id` → `jobs.on_collection_profile_changed`. Responses report `affected_clip_ids`.

- [ ] **Step 1: Failing tests** — CRUD round-trips; conflicts; profile/asset/collection-profile edits mark exactly the affected clips pending and queue renders; `seasons/resolve` returns `collection_id`; processing profile invalid settings → 422; asset upload/probe/delete conflict; settings rejects `remote.x` and protected entity; `gc/run` returns result; state never leaks the full token.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(studio): add organize, profiles, assets, settings and state endpoints`.

## Task 9: UI API — clips, uploads, recipe, streams, thumbnails, test on device, jobs

**Model:** Sonnet. **Branch:** `track/studio`.

**Files:** Create `uploads.py` (port SE; extensions `.mp4 .m4v .mov .mkv .avi .webm .ts`; default max from settings), `api_ui_clips.py`; Modify `app.py`; Test `tests/studio/test_uploads.py`, `tests/studio/test_api_ui_clips.py`.

Rules:
- Upload complete: new uuid clip, original moved to `originals/<id>/`, title from filename stem (`-`/`_` → spaces), recipe `Recipe(lead_in=settings.default_lead_in, tail_out=settings.default_tail_out)`, `enqueue_probe`.
- `PUT recipe`: `Recipe.validate_for(original)` (trim within duration ±0.05, `trim_start < trim_end`, crop inside source dims and ≥ 64×64, fades ≥ 0 and sum ≤ trimmed length, lead/tail 0…10, gain −24…24, `profile_id` exists or null) → `set_recipe` → `enqueue_render`.
- Streams: `FileResponse` with Range (`video/mp4`); `render` serves the published render; 404 when missing.
- Thumbs: `poster.jpg` from `thumbs/<clip_id>/r<n>/` of the published render (fallback `thumbs/<clip_id>/original/poster.jpg`); `filmstrip.json` and `filmstrip/{index}.jpg` from `thumbs/<clip_id>/original/` (index int 0…count-1).
- Source repair: `POST clips/{id}/source {upload_id}` — upload session must be complete (all bytes); file probed (must have video); stored with `store_original` (replacing the old original dir atomically: write new dir, swap, delete old); `set_original` with new sha256; `needs_source=False`; `enqueue_thumbs`; `enqueue_render`. Works for any clip (also replaces a good source).
- Test on device: target from `settings.test_targets` (404 unknown); re-check entity starts with `media_player.` and is not in `protected_entities` (403); source `render` → media-source URI of the published render; `preview` → copy preview to `renders/_test/<clip_id>-<token_hex(4)>.mp4` (deleted after 1 h by the periodic task; `_test` is excluded from `scan_renders`) and use its media-source URI; `supervisor.call_service("media_player", "play_media", {"entity_id", "media_content_id", "media_content_type": "video"})`; supervisor unavailable → 503.
- Delete clip: `repo.delete_clip` (render retired, GC removes later); delete original dir and thumbs immediately.

- [ ] **Step 1: Failing tests** — chunked upload of a generated mp4 → ready after `wait_idle` with poster/filmstrip; oversize 413; bad extension 415; recipe validation errors (one per rule); preview flow; bulk enable/collection/profile; streams with Range 206; thumbs endpoints; test-on-device payload recorded with a fake supervisor; protected entity 403; source repair clears `needs_source` and queues render; jobs ordering.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(studio): add clip, upload, recipe, stream, thumbnail and test-on-device endpoints`.

## Task 10: App packaging

**Model:** Sonnet. **Branch:** `track/studio`.

**Files:** Create `app/Dockerfile`, `app/.dockerignore`, `app/rootfs/usr/bin/cinema-studio`, `app/DOCS.md`, `app/CHANGELOG.md`, `app/translations/{en,es}.yaml`, `app/icon.png`, `app/logo.png`; Test `tests/studio/test_app_package.py`.

Port SE's Dockerfile and entry script (rename; pip pins `fastapi==0.115.14 uvicorn[standard]==0.32.1 httpx==0.28.1 pydantic==2.11.7 python-multipart==0.0.20`; `apk add --no-cache ffmpeg`). Icons: amber rounded square with a white film-strip glyph (draw with a small Python script using only stdlib `zlib`/`struct` PNG writer, or copy SE's generator approach). DOCS.md: what it does, first steps, import from Cinema Collections, discovery/manual connection, storage and GC rules, backup notes (renders live in `/media`, outside App backups).

- [ ] **Step 1: Failing test** (port SE `test_app_package.py`: base image, COPY sources exist, entry script mode `100755`, translations parse, PNG magic).
- [ ] **Step 2–4:** FAIL → implement → PASS. The Docker build needs `app/ui` from Track C, so it runs only in Task 22 after the merge (the package test skips the `ui/package.json` assertion when `app/ui` is absent).
- [ ] **Step 5: Commit** `build(studio): package the Supervisor App`.

---
# Track B — Integration `cinema_studio`

Tests in `tests/integration/`, `pytestmark = pytest.mark.integration`, using `pytest-homeassistant-custom-component`. `tests/integration/conftest.py` ports SE's (`enable_custom_integrations` autouse, `catalog_payload` fixture) and adds `media_root` (tmp dir patched into `hass.config.media_dirs = {"local": str(media_root)}`) plus a `make_render_file(clip_id, render_id, n, size)` helper writing a file of exactly `size` bytes at the catalog path.

## Task 11: Pure modules — catalog, timing, seasons, history, activation

**Model:** Luna. **Branch:** `track/integration`.

**Files:** Create `custom_components/cinema_studio/{const,catalog,seasons,history,activation}.py`; Test `tests/integration/test_catalog.py`, `test_seasons.py`, `test_history.py`, `test_activation.py`; Modify `tests/contract/test_season_cases.py` (integration half).

**Interfaces (Produces):**

```python
# const.py
DOMAIN = "cinema_studio"
EVENT_CATALOG_CHANGED = "cinema_studio_catalog_changed"
EVENT_SELECTED = "cinema_studio_selected"
CONF_HOST, CONF_PORT, CONF_TOKEN = "host", "port", "token"
CONF_SEASON_ENTITY, CONF_SCAN_INTERVAL = "season_entity", "scan_interval"
CONF_HISTORY_RESET_MODE, CONF_HISTORY_RESET_TIME = "history_reset_mode", "history_reset_time"
DEFAULT_PORT = 8099; DEFAULT_SCAN_INTERVAL = 30
STORAGE_VERSION = 1; REGULAR = "regular"; CONTRACT_VERSION = 1
MEDIA_SUBDIR = "cinema-studio"; RENDERS_SUBDIR = "cinema-studio/renders"
PIN_TTL = timedelta(hours=6)
LEGACY_DOMAIN = "cinema_collections"

# timing.py — already provided by Task 1; do not edit (integration only calls timing_problems, never re-rounds)

# catalog.py
@dataclass(frozen=True) class SeasonDef: id; name; color; icon; start: str | None; end: str | None; priority: int; collection_id: str
@dataclass(frozen=True) class CollectionDef: id; name; color; icon; playback_mode: str; order: tuple[str, ...]; enabled: bool
@dataclass(frozen=True) class RenderDef: id; n: int; relative_path: str; media_path: str; size: int; sha256: str
    timing: Timing; timing_source: str; profile_fingerprint: str; integrated_lufs: float | None
@dataclass(frozen=True) class ClipDef: id; collection_id; title; source_name; enabled: bool; sort_key: str
    render_pending: bool; render: RenderDef
@dataclass(frozen=True)
class Catalog:
    contract_version: int; revision: int; instance_id: str
    seasons: tuple[SeasonDef, ...]; collections: tuple[CollectionDef, ...]; clips: tuple[ClipDef, ...]
    invalid_clip_ids: tuple[str, ...]          # clips dropped at parse (timing problems, bad path)
    def find_collection(self, ref: str) -> CollectionDef | None    # id exact, else casefold id/name
    def find_season(self, ref: str) -> SeasonDef | None
    def render_ids(self) -> frozenset[str]
EMPTY_CATALOG: Catalog
def parse_catalog(data: Mapping[str, Any]) -> Catalog
    # ValueError on structural problems or contract_version != 1; per-clip problems (non-finite numbers,
    # timing_problems non-empty, relative_path not starting with "cinema-studio/renders/<clip_id>/", or ".."
    # anywhere) drop the clip into invalid_clip_ids instead of failing the catalog.

# seasons.py — copy of studio seasons.py plus:
class UnknownSeasonError(ValueError): ...
def resolve_effective_season(catalog: Catalog, day: date, *, action_season: str | None,
                             override: str | None, entity_state: str | None) -> tuple[str, str]
    # as SE: (season_id, source) source ∈ {"action","override","entity","calendar","default"};
    # entity_state matches season id or name casefold ("Halloween" → "halloween"); "unknown"/"unavailable"/"" ignored

# history.py — port of cinema_collections/history.py PlaybackHistoryStore logic as a PURE class over a dict
#   (persistence lives in manager.py):
class HistoryState:
    def __init__(self, data: Mapping[str, Any] | None = None) -> None   # {"collections": {id: record}}
    def to_dict(self) -> dict[str, Any]
    def pick(self, collection_id: str, eligible: Sequence[str], mode: str, rng: random.Random,
             *, now: datetime, reset_mode: str, reset_time: time) -> tuple[str | None, int, bool, dict[str, Any] | None]
        # returns (clip_id, round_number, history_reset, new_record) — new_record None when nothing to pick;
        # semantics identical to PlaybackHistoryStore.async_select incl. daily reconcile; never mutates self
    def commit(self, collection_id: str, record: dict[str, Any]) -> None
    def reset(self, collection_id: str | None, now: datetime) -> list[str]
    @classmethod
    def from_legacy(cls, legacy: Mapping[str, Any], known_clip_ids: set[str]) -> HistoryState
        # legacy Store payload of cinema_collections; records copied verbatim incl. period_start (daily-mode
        # parity); unknown clip ids dropped from played_clip_ids

def order_candidates(clips: Sequence[ClipDef], collection: CollectionDef) -> list[str]
    # random: catalog order; sequential: sorted by (sort_key.casefold(), sort_key, id);
    # custom: collection.order ids present, then the rest sequential (Clips selection.py semantics)

# activation.py
@dataclass(frozen=True)
class ActivationState:
    last_effective_season: str | None; last_effective_collection: str | None
def evaluate_activation(state: ActivationState, *, season_id: str, collection_id: str,
                        fallback: bool) -> tuple[ActivationState, str | None]
    # returns (new_state, collection_to_reset or None):
    #  state empty (first run) → store, no reset
    #  season changed & not fallback → reset collection_id
    #  season changed & fallback → store, no reset
    #  season same & collection changed & not fallback → reset collection_id
    #  otherwise unchanged, None
```

- [ ] **Step 1: Failing tests** — catalog: production-like payload parses; `contract_version: 2` → ValueError; clip with `NaN` duration, bad tail, or path `cinema-studio/renders/other/x.mp4` → in `invalid_clip_ids`; `find_collection("Regular")`. Seasons precedence table (as SE) + entity "Halloween" match. History: port every test in `~/Dev/hass-clips-manager/tests/` that targets `PlaybackHistoryStore` selection semantics to `HistoryState.pick/commit` (random no-repeat round, round rollover sets `history_reset`, sequential first-unplayed, custom order, removed clip leaves round, reappearing clip joins, daily reset mode), plus `from_legacy` drops unknown ids. `order_candidates` table. Activation table: one test per rule. Contract halves pass.
- [ ] **Step 2–4:** FAIL → implement → PASS (`uv run pytest tests/integration/test_catalog.py tests/integration/test_seasons.py tests/integration/test_history.py tests/integration/test_activation.py tests/contract -q`, pyright, ruff).
- [ ] **Step 5: Commit** `feat(integration): add catalog parsing, timing checks, seasons, ported history and activation rules`.

## Task 12: File verification and consumer fence

**Model:** Sol. **Branch:** `track/integration`.

**Files:** Create `custom_components/cinema_studio/{verify,fence}.py`; Test `tests/integration/test_verify.py`, `tests/integration/test_fence.py`.

**Interfaces:**

```python
# verify.py (all functions are blocking; callers use hass.async_add_executor_job)
def render_path(media_root: Path, render: RenderDef) -> Path      # media_root / render.relative_path
def verify_render(media_root: Path, render: RenderDef) -> bool
    # True only if: path.is_symlink() is False; os.path.realpath(path) is inside
    # realpath(media_root / "cinema-studio/renders") + os.sep; stat.S_ISREG; st_size == render.size
def verify_all(media_root: Path, renders: Iterable[RenderDef]) -> dict[str, bool]

# fence.py (blocking)
class FenceTimeout(Exception): ...
class FenceCorrupt(Exception): ...          # existing consumer file present but unparseable: never overwritten
PIN_GRACE = timedelta(minutes=10)           # same margin as App GC
@dataclass(frozen=True)
class FenceWriteResult:
    written: bool                           # False only when before_write returned False
    pins: dict[str, datetime]               # merged pins as written (unchanged on-disk pins when not written)
@dataclass
class ConsumerState:
    consumer_id: str; generation: str; seq: int
    held_revision: int; held_render_ids: set[str]; pins: dict[str, datetime]   # render_id → expires_at (UTC)
class ConsumerFence:
    def __init__(self, media_root: Path, consumer_id: str, generation: str) -> None
    def write(self, *, held_revision: int, held_render_ids: Iterable[str], new_pins: Mapping[str, datetime],
              persisted_pins: Mapping[str, datetime], now: datetime, timeout: float = 5.0,
              before_write: Callable[[], bool] | None = None) -> FenceWriteResult
        # 1. flock(LOCK_EX) consumers/<id>.lock (retry LOCK_NB every 50 ms until timeout → FenceTimeout)
        # 2. flock(LOCK_SH) .gc.lock (same retry; FenceTimeout)
        # 3. read existing file: missing → treat as empty; present but unparseable → release locks and raise
        #    FenceCorrupt (file left untouched; App GC also halts on it; manager surfaces repair issue
        #    `consumer_file_corrupt` and selection raises not_ready until a human removes/repairs it)
        # 4. if before_write is given and returns False → release, return FenceWriteResult(False, existing pins)
        #    (selection uses this to stat-verify the render while GC is excluded)
        # 5. merged pins = union(existing, persisted_pins, new_pins) keeping the later expires_at; a pin is
        #    dropped only when expires_at + PIN_GRACE < now (retained through the skew margin)
        # 6. write JSON to <id>.json.tmp, fsync, os.replace, fsync dir; seq += 1
        # 7. release both locks (reverse order); return FenceWriteResult(True, merged)
```

- [ ] **Step 1: Failing tests** — verify: correct file true; wrong size false; symlink false; path escaping via `..` in relative_path false; directory false; missing false. Fence: write creates file with exact keys; pins merge keeps later expiry and never drops unexpired on-disk pins written by a previous generation; pin expired 5 min ago retained, expired 11 min ago dropped; unparseable existing file → `FenceCorrupt` and file bytes unchanged; `before_write` False → `written False`; `held_render_ids` replaced; `seq` increments; `before_write` returning False writes nothing; another process holding `LOCK_EX` on `.gc.lock` (multiprocessing, 1 s) → `FenceTimeout` with timeout 0.2 and success with timeout 3; two threads writing concurrently with different new pins → final file contains both (serialized by the consumer lock).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(integration): add render verification and flock consumer fence`.

## Task 13: Client, config flow, setup, coordinator, snapshot adoption

**Model:** Sonnet. **Branch:** `track/integration`.

**Files:** Create `api.py`, `coordinator.py`, `config_flow.py`, `__init__.py`, `services.py` (placeholder `async_register_services`), `translations/{en,es}.json` (config + options); Test `tests/integration/test_api.py`, `test_config_flow.py`, `test_init.py`.

Port SE `api.py`, `coordinator.py`, `config_flow.py`, `__init__.py` structure, with these changes:
- `StudioClient(session, host, port, token, consumer_id)` sends `X-Cinema-Consumer`; methods `health()`, `catalog(etag)`, `post_selections(events)`, `legacy_stage(body) -> dict`, `legacy_commit(body) -> dict` (legacy calls use a 30 min timeout).
- Options flow: `season_entity` (EntitySelector `sensor|input_select|select|input_text`), `scan_interval` (10–3600), `history_reset_mode` (`on_exhaustion|daily`), `history_reset_time` (TimeSelector, default `00:00`).
- Coordinator `CinemaStudioCoordinator(hass, entry, client, snapshot_store)`: `async_load_snapshot()`; on each new catalog (200): parse (ValueError → keep previous, log, repair issue `invalid_catalog`), then `await manager.async_install_snapshot(catalog, raw, persist=self._snapshot.async_save)` (the manager persists and swaps under its lock), and only after it returns update `self.data`. 304 keeps catalog. Connection error with catalog → `connected=False`; without → `UpdateFailed`; auth → `ConfigEntryAuthFailed`.
- `async_setup_entry`: client, snapshot `Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.catalog")`, coordinator, order: `had_snapshot = await coordinator.async_load_snapshot()` → manager (Task 14) `await manager.async_setup()` (loads history/pins/activation, declares the snapshot under the fence, verifies files) → `await coordinator.async_refresh()`; `ConfigEntryNotReady` when no snapshot and refresh failed. Until Task 14 lands, a stub manager whose `async_install_snapshot` just awaits `persist(raw)` is acceptable in this task's tests.

- [ ] **Step 1: Failing tests** — port SE `test_api.py`, `test_config_flow.py`, `test_init.py` adapted (consumer header present; legacy endpoints; options fields; `async_install_snapshot` is awaited before `coordinator.data` changes and a raising install keeps the previous data; invalid catalog keeps previous snapshot).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(integration): add studio client, config flow, coordinator and snapshot adoption`.

## Task 14: Selection manager and actions

**Model:** Sol. **Branch:** `track/integration`.

**Files:** Create `manager.py`, `services.yaml`, `icons.json`; Replace `services.py`; Modify `__init__.py`, translations (services + exceptions + issues); Test `tests/integration/test_manager.py`, `tests/integration/test_services.py`, `tests/integration/test_contract_response.py`.

**Interfaces:**

```python
class CinemaStudioManager:
    def __init__(self, hass: HomeAssistant, entry: CinemaStudioConfigEntry, coordinator: CinemaStudioCoordinator,
                 *, rng: random.Random | None = None, now: Callable[[], datetime] = dt_util.utcnow) -> None
    async def async_setup(self) -> None
        # load Store f"{DOMAIN}.{entry_id}.state" = {"history":…, "pins":{render_id: iso}, "activation":{…},
        #   "selection_queue":[…]}; generation = uuid4().hex; the coordinator has ALREADY loaded the cached
        #   snapshot (async_load_snapshot runs before manager setup); fence.write(held = snapshot render ids,
        #   persisted pins) and verify_all; FenceCorrupt → not ready + repair issue; mark ready; register
        #   midnight + override/entity listeners
    async def async_install_snapshot(self, catalog: Catalog, raw: dict[str, Any],
                                     persist: Callable[[dict[str, Any]], Awaitable[None]]) -> None
        # ONE serialized transition under self._lock (selection waits):
        #  a. fence.write(held_revision=old.revision, held_render_ids=old ∪ new render ids, new_pins={}, …)
        #     — protects both snapshots during the switch
        #  b. verify_all(new catalog) in executor
        #  c. await persist(raw)   (coordinator's Store.async_save of the raw catalog)
        #  d. swap: self._catalog = catalog, self._verified = verification map (coordinator data updated by caller
        #     only after this returns)
        #  e. fence.write(held_revision=new.revision, held_render_ids=new render ids, …)
        # Any exception in a–c: nothing swapped, fence still holds old ∪ new (safe superset), exception propagates
        # (coordinator keeps old snapshot, retries next poll). Exception in e: logged; superset stays (safe).
    @property
    def ready(self) -> bool
    async def async_select(self, *, collection_ref: str | None, season_ref: str | None, dry_run: bool) -> dict[str, Any]
    async def async_reset(self, collection_ref: str | None) -> list[str]
    async def async_evaluate_activation(self) -> None     # midnight / override / entity changes
    def last_selection(self, collection_id: str) -> dict[str, Any] | None
```

`async_select` algorithm (under `self._lock`; not ready → `ServiceValidationError(translation_key="not_ready")`):
1. Resolve season (`season_ref` → action; override select state unless `Auto`; `season_entity` state; calendar at local date; default). Unknown action season → `unknown_season`. If `collection_ref` given → that collection (unknown → `unknown_collection`), no season mapping, no activation.
2. Else collection = season's `collection_id`; candidates = `order_candidates(enabled clips of that collection with verified render)`; empty or collection missing/disabled → fallback to regular season's collection (`season_fallback = True`); still empty → `no_playable_clip`.
3. Activation (skip when `dry_run` or `season_ref` or `collection_ref`): `evaluate_activation(...)`; reset collection → `history.reset(...)` and `activation_reset = True`.
4. Loop: `history.pick(...)` → candidate id (None → `no_playable_clip`). Then in executor: `fence.write(..., new_pins={render_id: now + PIN_TTL} if not dry_run else {}, before_write=lambda: verify_render(...))`; `before_write` False → mark unverified, remove from candidates, repeat (max len(candidates)); `FenceTimeout` → `not_ready`. For `dry_run` the fence is still taken (so the verification is equally strong) but no pin is added and nothing is persisted.
5. Not dry run: `history.commit`, update `self._pins` from the fence result, append the selection event to `selection_queue`, then ONE `await store.async_save({history, pins, activation, selection_queue})` **before** returning (no delayed save); after saving schedule a fire-and-forget flush (`client.post_selections`; on success remove sent events and save); fire `EVENT_SELECTED`. A failed save raises (no response returned).
6. Response dict per the Home Assistant contract; `media_content_id = "media-source://media_source/local/" + render.relative_path`; `relative_output_path = render.relative_path`; `duration_seconds == duration == render.timing.duration`; `output_is_stale == render_pending`; `selection_id = uuid4().hex`; `selected_at` ISO Z.

Actions (`services.py`): `select_next_clip` (`SupportsResponse.OPTIONAL`; fields `collection_id`, `season`, `dry_run`), `reset_history` (`collection_id`), `refresh`, `import_legacy` (`history_only`, Task 15 implements; register here with a handler that calls `manager.legacy.async_run(history_only)`), errors as `ServiceValidationError` with translation keys from the constraints.

- [ ] **Step 1: Failing tests** — `test_contract_response.py`: response validates against `contract/selection_response.schema.json`, `media_content_id` contains `clip_id`; manager: offline (client raising) still selects from snapshot; unverified file (wrong size) skipped and the next candidate returned; all unverified → `no_playable_clip`; GC fence held exclusively by another process → `not_ready`; pins file contains the selected render with 6 h expiry; dry_run writes no pin, no history, no activation; sequential returns first unplayed and exhausts into a new round with `history_reset`; season change resets ordered collection once (`activation_reset` true) and not again after restart (reload entry); per-call `season` doesn't touch activation; fallback to regular when collection empty with `season_fallback`; history persisted before return (Store mock saved); snapshot install is one transition (selection blocked during it; failure keeps old catalog and superset fence); corrupt consumer file → `not_ready` + repair issue; selection queue retried after a failed post.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(integration): add fenced, offline selection manager and actions`.

## Task 15: Legacy import (integration side)

**Model:** Sol. **Branch:** `track/integration`.

**Files:** Create `custom_components/cinema_studio/legacy.py`; Modify `manager.py` (attach), `services.py`; Test `tests/integration/test_legacy.py`.

**Interfaces:**

```python
class LegacyImport:
    def __init__(self, hass: HomeAssistant, manager: CinemaStudioManager, client: StudioClient) -> None
    async def async_run(self, history_only: bool) -> dict[str, Any]   # returns the LegacyReport (or {"history": n})
```

Steps:
1. Find the single loaded `cinema_collections` config entry (`hass.config_entries.async_entries(LEGACY_DOMAIN)`); none → `ServiceValidationError("legacy_not_found")`.
2. Legacy HTTP client: aiohttp session, base `entry.data["endpoint"]`, header `Authorization: Bearer <entry.data["token"]>` (never logged, never returned). GET `/api/v1/status` (queue depth, current job), `/api/v1/clips`, `/api/v1/collections`, `/api/v1/profiles`, `/api/v1/assets`, `/api/v1/jobs` (active = state in `queued|running`). Shapes: see `~/Dev/hass-clips-manager/custom_components/cinema_collections/api_client.py` and `models.py`.
3. Seasons block: from `input_datetime.party_halloween_inicio/_fin` and `party_christmas_inicio/_fin` states (`YYYY-MM-DD` → `MM-DD`) when present: `halloween` (priority 10, collection `halloween` if a Worker collection with that id exists else `regular`), `christmas` (priority 20, collection `christmas` if exists else `regular`), plus `regular` → `regular`.
4. Roots: `{"source": "/media/cinema-collections/source", "compiled": "/media/cinema-collections/compiled"}` (production defaults, also readable from the legacy status payload when it exposes them).
5. `history_only=False`: `client.legacy_stage({"phase": "stage", "manifest": …})` → re-fetch `/api/v1/clips` → `client.legacy_commit({"phase": "commit", "run_id", "clips": refetched})` → `await coordinator.async_request_refresh()` and wait until the catalog revision ≥ the report's revision (max 60 s).
6. History (both modes): copy the legacy entry options `history_reset_mode` / `history_reset_time` into this entry's options when they differ from defaults (`hass.config_entries.async_update_entry`); load `Store(hass, 1, f"cinema_collections.{legacy_entry.entry_id}.playback_history")` read-only (records keep `period_start`, `round_number`, `played_clip_ids`, `last_selected_clip_id`, `last_reset_at`, `reset_pending`); `HistoryState.from_legacy(data, known_clip_ids=catalog clip ids)`; replace the manager's history for the legacy collection ids present; seed activation with the current effective season/collection (no reset); persist.
7. Return report (+ `history_collections` count). Fires a persistent notification summarizing counts.

- [ ] **Step 1: Failing tests** — `aioclient_mock` legacy Worker + studio endpoints: full run calls stage then commit with re-fetched clips; bearer from entry data and never present in the returned dict or logs (`caplog`); missing legacy entry error; seasons built from input_datetime states; history imported with unknown ids dropped and activation seeded so the next selection doesn't reset; `history_only` skips stage/commit.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(integration): add legacy Cinema Collections import service`.

## Task 16: Entities, diagnostics, brand

**Model:** Sonnet. **Branch:** `track/integration`.

**Files:** Create `entity.py`, `sensor.py`, `select.py`, `binary_sensor.py`, `diagnostics.py`, `brand/icon.png`; Modify translations (entity names), `icons.json`; Test `tests/integration/test_entities.py`, `tests/integration/test_diagnostics.py`.

Port SE entity modules:
- `sensor.cinema_studio_active_season` (state season id; attrs `name`, `source`, `collection_id`, `last_effective_season`, `color`).
- `select.cinema_studio_season_override` (`Auto` + season names; RestoreEntity; change → `manager.async_evaluate_activation()`).
- `sensor.cinema_studio_<collection>_last` per collection (added/removed with catalog): state last title; attrs `clip_id`, `render_id`, `media_content_id`, `duration`, `season`, `selected_at`, `available` (verified playable count).
- `sensor.cinema_studio_catalog`: state revision; attrs `clips`, `playable`, `unverified`, `invalid`, `pins`.
- `binary_sensor.cinema_studio_studio_connected` (connectivity, diagnostic; attrs `catalog_revision`, `last_sync`, `app_version`).
- Diagnostics redact `token`; include catalog summary, verification map counts, pins, activation, history sizes.

- [ ] **Step 1: Failing tests** (port SE `test_entities.py` structure) — states/attrs above; override restore; per-collection sensors follow catalog; diagnostics redaction.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(integration): add entities, diagnostics and brand`.

---
# Track C — UI (Vue 3 + Tailwind 4)

All UI work under `app/ui/`, built into `app/src/cinema_studio/static/ui` by the Dockerfile. Tests with vitest + @vue/test-utils, `ui` client mocked. Start by copying the entire `~/Dev/hass-sound-effects/app/ui/` tree (package.json, configs, `src/`), then rename and replace audio-specific parts as each task says. Shared components kept verbatim: `Icon`, `NavBar`, `Sheet`, `ConfirmDialog` (+`useConfirm`), `Toast` (+`useToast`), `JobTray`, `IconPicker`, `ColorPicker`, `SeasonTimeline`, `SeasonForm`, `ProfileForm`, `useModal`.

## Task 17: UI foundation

**Model:** Sonnet. **Branch:** `track/ui`.

**Files:** Copy SE `app/ui/**`; Modify `package.json` (name `cinema-studio-ui`, remove `wavesurfer.js`), `src/style.css` (accent tokens), `src/api/{types,client}.ts`, `src/i18n/{en,es}.ts`, `src/lib/{format,recipe,filters}.ts`, `src/composables/{useStudio,useJobs,usePlayer}.ts`, `src/App.vue`, `src/router.ts`; Delete audio-only files (`lib/audioEngine.ts`, `lib/peaks.ts`, `composables/useEditorAudio.ts`, `useEditorPreview.ts`, `components/TagEditor.vue`, `AuditionTargets.vue`, `ImportBrowser.vue` and their specs); Tests updated specs.

Changes:
- `style.css`: `--color-accent: #f59e0b; --color-accent-soft: #f59e0b33; --color-accent-ink: #111111;` (rest as SE).
- `api/types.ts`: exactly the Shared API Reference types. `api/client.ts`: `ui = { state, token, rotateToken, settings, collections{list,create,update,remove,order}, seasons{list,create,update,remove,resolve}, normProfiles{list,create,update,remove,apply}, procProfiles{list,create,update,remove}, assets{list,upload(file),remove}, clips{list,get,update,putRecipe,preview,rerender,remove,bulk,test,replaceSource}, uploads{create,chunk,complete}, jobs, gcRun }`; `mediaUrl(id, kind: "original"|"preview"|"render", bust?)` → `api/ui/clips/${id}/${kind}`; `posterUrl(id, bust?)`, `filmstripUrl(id, index, bust?)`.
- `lib/format.ts`: keep SE formatters; `formatDuration(154.133)` → `"2:34.1"`; add `formatTimecode(seconds)` → `"00:02:34.133"`.
- `lib/recipe.ts`: `defaultRecipe(settings)`, `validateRecipe(r, original)` returning i18n keys for every server rule in Task 9, `recipesEqual`, `trimmedLength(r, duration)`.
- `lib/filters.ts`: `ClipFilter = {collectionId, seasonId, query, status}`; `filterClips` (accent-insensitive title/source_name), `loudnessSpread(clips)` over `render.integrated_lufs`.
- `useStudio`: loads state, collections, seasons, normProfiles, procProfiles, assets, clips.
- `usePlayer`: single shared `HTMLVideoElement` for inline card previews (muted autoplay disabled; play/pause toggle).
- Nav items: Library `mdiFilmstripBox`, Upload `mdiUpload`, Organize `mdiShapeOutline`, System `mdiCog`; logo text "Cinema Studio". i18n locale key `cinema-locale`.

- [ ] **Step 1: Failing tests** — format (`formatTimecode`), recipe validation table, filters, i18n completeness (es has all en keys), client paths for every `ui.*` method (fetch mock asserts URL + method).
- [ ] **Step 2–4:** `npm --prefix app/ui run test:unit` FAIL → implement → `test:unit` + `build` PASS.
- [ ] **Step 5: Commit** `feat(ui): add Cinema Studio UI foundation, API client and i18n`.

## Task 18: Library view

**Model:** Luna. **Branch:** `track/ui`.

**Files:** Modify `src/views/LibraryView.vue`; Create/rename `src/components/{CollectionChips.vue,ClipCard.vue,BulkBar.vue,LoudnessStrip.vue,CustomOrderList.vue,ProfilePicker.vue}`; Tests `src/components/{CollectionChips,ClipCard,BulkBar,CustomOrderList}.spec.ts`.

Behavior (port SE LibraryView/SoundItem/BulkBar/LoudnessStrip patterns):
- Toolbar: search (150 ms debounce), season filter (filters by the season's collection), status filter; state in route query.
- `CollectionChips`: "All" + per collection (icon, color, count, mode badge random/sequential/custom).
- `ClipCard`: poster (`posterUrl`, lazy, 16:9, fallback icon), title, duration (`render.duration`), content length, LUFS, status pill, pending badge (`render_pending`), `needs_source` warning badge, disabled dim. Click → `/clips/:id`. Play button opens an inline `<video>` preview of `mediaUrl(id, "render")`.
- `LoudnessStrip` per collection (≥ 2 clips with LUFS): spread + "Level this collection" → `ProfilePicker` → `normProfiles.apply(id, {collection_id})`.
- `CustomOrderList` (shown when the selected collection mode is `custom`): reorderable list (drag handle with pointer events + up/down buttons for accessibility) → `collections.order(id, clip_ids)`; shows the position numbers the integration will follow.
- Multi-select (checkbox/long-press 450 ms) + `BulkBar`: Move to collection, Enable, Disable, Normalize (profile or None), Re-render, Delete (confirm).
- Empty states: no clips → "Upload clips" and "Import from Cinema Collections" (System); no matches → clear filters.

- [ ] **Step 1: Failing tests** — chips counts and v-model; ClipCard renders duration/LUFS/badges and emits open/play/select; BulkBar actions; CustomOrderList moving an item emits the new id order and calls the client.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(ui): add clip library with posters, custom order and bulk actions`.

## Task 19: Upload and Organize views

**Model:** Sonnet. **Branch:** `track/ui`.

**Files:** Modify `src/views/{UploadView,OrganizeView}.vue`, `src/composables/useUpload.ts`; Create `src/components/{CollectionForm.vue,ProcessingProfileForm.vue,AssetsPanel.vue}`; Tests `src/composables/useUpload.spec.ts`, `src/components/{CollectionForm,ProcessingProfileForm}.spec.ts`.

- Upload: SE flow with video extensions, batch default = collection only; per-file progress; done rows link to the editor.
- Organize tabs: **Collections** (name, icon, color, playback mode with explanation text for each mode, processing profile select, enabled; delete with 409 message), **Seasons** (SE SeasonTimeline + SeasonForm extended with `collection_id` select; date probe shows season + collection), **Loudness profiles** (SE ProfileForm), **Processing profiles** (`ProcessingProfileForm`: sections Video — resolution preset 4K/1080p/720p + fps + crf + maxrate; Audio — bitrate/sample rate; Loudness — two-pass on/off + LUFS/TP/LRA; Fades — in/out seconds; Intro/Outro — asset selects + transition seconds; "Advanced JSON" textarea showing the full settings, validated server-side), **Assets** (`AssetsPanel`: list with ready/missing status, upload, delete; missing assets highlighted with "Upload <filename>" call to action).

- [ ] **Step 1: Failing tests** — useUpload chunking/concurrency (port SE spec); CollectionForm emits payload with mode; ProcessingProfileForm round-trips settings JSON and maps 4K preset to 3840×2160 scaling width/height.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(ui): add upload and organize views for collections, seasons and profiles`.

## Task 20: Clip editor

**Model:** Sol. **Branch:** `track/ui`.

**Files:** Create `src/views/ClipEditorView.vue`, `src/components/{VideoStage.vue,FilmstripTimeline.vue,CropOverlay.vue,TransportBar.vue,TestDeviceDialog.vue}`, `src/lib/{timeline.ts,crop.ts}`, `src/composables/useClipEditor.ts`; Tests `src/lib/{timeline,crop}.spec.ts`, `src/views/ClipEditorView.spec.ts`.

```ts
// lib/timeline.ts
export function timeToX(t: number, duration: number, width: number): number
export function xToTime(x: number, duration: number, width: number): number      // clamped 0..duration
export function snapTime(t: number, fps: number | null): number                  // to frame grid when fps known, else 0.01 s
export function frameIndexForTime(t: number, interval: number, count: number): number
// lib/crop.ts
export type Rect = { x: number; y: number; w: number; h: number }
export function clampCrop(r: Rect, srcW: number, srcH: number, min = 64): Rect     // inside source, even values, ≥ min
export function cropFromDisplay(r: Rect, displayW: number, displayH: number, srcW: number, srcH: number): Rect
export function displayFromCrop(r: Rect, displayW: number, displayH: number, srcW: number, srcH: number): Rect
export function aspectLock(r: Rect, aspect: number, anchor: "nw"|"ne"|"sw"|"se"): Rect
// composables/useClipEditor.ts
export function useClipEditor(clipId: Ref<string>): { clip, recipe (Ref<Recipe>), dirty, problems, saving,
  save(): Promise<void>, previewRender(): Promise<void>, resetRecipe(): void, previewReady: Ref<boolean> }
```

Layout (route `/clips/:id`, full-screen `Sheet` on phones, two-column ≥ lg):
1. **VideoStage** — `<video>` of original (default), preview, or render (segmented control); `CropOverlay` (draggable/resizable rectangle with ≥ 24 px handles, aspect lock 16:9 toggle, "Reset crop") drawn over the video's content box; live CSS preview of fades via an opacity overlay and `video.volume` ramps while playing the original (fade simulation only; loudness heard in preview render).
2. **FilmstripTimeline** — thumbnails from `filmstrip.json` laid out across the width; trim handles (pointer + keyboard: arrows nudge one frame/0.01 s, shift ×10); playhead synced with the video (`requestAnimationFrame`); click to seek; region outside trim dimmed; margin indicators (lead/tail) drawn as black blocks before/after the trimmed region; numeric fields for trim start/end (timecode).
3. **TransportBar** — play/pause (space), loop trimmed region, jump to in/out, current timecode / trimmed length.
4. **Edit panel** — fades in/out (null = "Use profile (1.0 s / 1.5 s)" checkbox), gain dB slider, loudness profile picker (None = processing profile target), margins lead/tail (0–10 s), collection, title, enabled, notes.
5. **Render panel** — published render info (r<n>, duration, content start/end, LUFS, timing source, published date), pending/rendering status with job progress, missing-asset warning (link to Organize → Assets), and for `needs_source` a "Replace source file" button (file picker → chunked upload → `clips.replaceSource(id, upload_id)`). The filmstrip and trim fields are on the original's timeline.
6. **Footer actions** — "Preview render" (queues preview → plays it in VideoStage when done), "Test on device" (`TestDeviceDialog`: targets from settings, source preview/render, sends `clips.test`; empty targets → link to System), "Save & render" (disabled when unchanged or invalid; shows server validation errors), unsaved-changes guard.

- [ ] **Step 1: Failing tests** — timeline math (round trips, clamping, frame snap at 24 fps), crop math (clamp, even values, display↔source round trip within 2 px, aspect lock), editor view with mocked client: Save disabled when unchanged, enabled after trim change, sends `putRecipe` with crop in source pixels; invalid trim shows problem and disables Save; Test on device posts selected target.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(ui): add clip editor with filmstrip trim, crop, fades, loudness and device test`.

## Task 21: System view

**Model:** Luna. **Branch:** `track/ui`.

**Files:** Modify `src/views/SystemView.vue`; Create `src/components/{ConnectionPanel.vue,StoragePanel.vue,GcPanel.vue,TestTargets.vue,LegacyImportPanel.vue,JobsPanel.vue}`; Tests `src/components/{TestTargets,GcPanel,LegacyImportPanel}.spec.ts`.

Panels: **Connection** (SE ConnectionPanel), **Storage** (free space bar with reserve marker, originals/renders/retired/work bytes, network-fs warning), **Garbage collection** (enabled/halted reason, last run, deleted count, consumers table with file present/held revision/pins, "Run now" → `gcRun`), **Test devices** (`TestTargets`: label + `media_player.` entity only, rejects protected entities with explanation; protected list editable), **Defaults** (lead/tail seconds, max upload MB, max duration, disk reserve GB), **Legacy import** (`LegacyImportPanel`: last report counts and lists; instructions "Run the action `cinema_studio.import_legacy` from Home Assistant"), **Jobs**.

- [ ] **Step 1: Failing tests** — TestTargets rejects `remote.x` and `media_player.otocuma_dp`; GcPanel shows halted reason and calls `gcRun`; LegacyImportPanel renders counts from a report.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(ui): add system view with storage, GC, devices and legacy import status`.

---

## Task 22: Merge, end-to-end check, docs, publish, release

**Model:** Opus (orchestrator) + Sonnet for docs. **Branch:** `main`.

- [ ] **Step 1:** Merge `track/studio`, `track/integration`, `track/ui` into `main`; resolve conflicts only in shared files.
- [ ] **Step 2:** `scripts/verify.sh` → all green (Docker build included when the daemon is available).
- [ ] **Step 3: Cross-process smoke** — `tests/e2e/test_fence_e2e.py` (marked `e2e`, run in verify): start the Studio app (TestClient) with a tmp media root, publish two renders for one clip (r1 retired), write a consumer file via the integration's `ConsumerFence` holding r1 → GC keeps r1; rewrite without r1 and age it 49 h → GC deletes; concurrently hold the integration's shared lock in a subprocess while GC runs → GC waits/returns without deleting.
- [ ] **Step 4: Local UI smoke** — run Studio in dev mode (`CINEMA_STUDIO_DEV=1`, tmp data/media) with the built UI; in the browser pane at 375×812 and desktop: upload a generated mp4, open editor, trim + crop + fade, preview render, save & render, see r2; organize collections/seasons; no horizontal scroll, no console errors. Save screenshots to `docs/images/`.
- [ ] **Step 5: Docs** — `README.md` (features, screenshots, install: App repository URL + HACS custom repository, connecting, `cinema_studio.select_next_clip` example, import from Cinema Collections, Spanish quick start), `docs/installation.md`, `docs/usage.md`, `docs/automations.md` (response contract table + projector-script integration with fallback example), `docs/migration.md` (spec migration steps), `docs/ROLLBACK.md` (exact rollback per step), `app/DOCS.md` final, `app/CHANGELOG.md` `0.1.0`.
- [ ] **Step 6:** Commit docs; `gh repo create NaturalDevCR/hass-cinema-studio --public --source . --push --description "Import, edit, render and organize cinema clips for Home Assistant (App + HACS integration)"`; topics `home-assistant, hacs, home-assistant-addon, cinema, video`.
- [ ] **Step 7:** Watch CI until quality, validate and app-build succeed; fix failures.
- [ ] **Step 8:** `git tag v0.1.0 && git push origin v0.1.0 && gh release create v0.1.0 --title "v0.1.0" --notes-file app/CHANGELOG.md`.

## Task 23: Production migration (operational; Claude via HA MCP, each step agreed with Sol)

Follow the spec section "Production migration" exactly. Before each numbered step, send Sol the planned MCP calls and the current state; proceed only on agreement. Record every step, result and rollback handle in `docs/decisions/2026-10-05-migration-log.md`.

- [ ] **Pre-flight:** `ha_manage_backup(scope="snapshot", action="create", name="pre-cinema-studio-<date>")`; confirm `input_select.cinema_fase == "reposo"`, `script.cinema_reproducir` off, local time outside 17:00–02:00, old Worker `queue_depth == 0`.
- [ ] **Step 1:** `ha_manage_app(action="add_repository", repository="https://github.com/NaturalDevCR/hass-cinema-studio")`; install + start `*_cinema_studio`; `ha_manage_hacs(action="add_repository", repository="NaturalDevCR/hass-cinema-studio", category="integration")`; download; config check; restart HA; accept discovery flow (`ha_set_integration` on the discovered flow); set options `season_entity = sensor.temporada_de_cine_activa`. Verify `binary_sensor.cinema_studio_studio_connected` on.
- [ ] **Step 2:** `cinema_studio.import_legacy` (`history_only: false`); read report; expect 44 imported (+1 stale handled per rules), 0 skipped for unsafe paths. Investigate any rejection before continuing.
- [ ] **Step 3:** Parity: for every clip compare `sensor`/catalog render timing with the old Worker `metadata` (via `cinema_collections` diagnostics or `/api/v1/clips` through the old integration's data) and `shell_command.cinema_clip_metadata` for ≥ 5 clips per collection; ordered collections dry-run equality (both currently `random`, so compare manifests only).
- [ ] **Step 4:** Create `script.cinema_studio_selftest` (fields `forzar_respaldo`, `forzar_contrato_invalido`) containing the exact replacement block with `dry_run: true` on both services and a final `stop` with `response_variable` returning `{ruta, clip_uri, clip_id, clip_nombre, duracion, content_start, content_end, lead_in, tail_out, cierre_anticipado_habilitado, seleccion_contract}`; run three ways; all valid.
- [ ] **Step 5:** `import_legacy history_only: true`; create `script.cinema_reproducir_v1_backup` (exact copy of the current config); replace only the selection + metadata steps of `script.cinema_reproducir` with the selftest-proven block (without `dry_run`); diff every other step equal to the backup; record config hashes.
- [ ] **Step 6:** Leave enabled: old App, old integration, `automation.pre_compile_cinema_clips`, `automation.cinema_clips_reiniciar_historial_al_cambiar_de_temporada`.
- [ ] **Step 7:** Write the morning report (Spanish) with: what changed, links, rollback one-liner, observation exit gate, open items (missing intro asset upload, first evening session to watch).
