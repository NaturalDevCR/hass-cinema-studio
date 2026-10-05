# Cinema Studio — brainstorming handoff (2026-10-05)

Started in a hass-sound-effects session; continue here. Brainstorming is
mid-way: scope, approach and phases are approved by the user. Next steps are
listed at the end.

## Goal

Rebuild the cinema clips product (today: `~/Dev/hass-clips-manager`, App
"Cinema Collections Worker" + HACS integration `cinema_collections`) on the
architecture and UI of `~/Dev/hass-sound-effects` (App "Sound Effects Studio" +
integration `sound_effects`), which the user loves ("the flow, everything"), and
improve it substantially for cinema clips.

## Approved decisions

1. **Scope: architecture + UI**, delivered in phases while production cinema
   keeps working.
2. **Seasons native to Cinema Studio**, independent from Sound Effects seasons
   (same model: yearly date ranges, priority, HA override `select`). They
   replace `sensor.temporada_de_cine_activa` and the automation
   `automation.cinema_clips_reiniciar_historial_al_cambiar_de_temporada`.
3. **Keep the three playback modes** exactly as today: `random` (no-repeat
   history), `sequential`, `custom` (visual order). Entering a season must start
   ordered modes from the first clip (today done by the reset automation).
4. **Editor improvements, all requested:** better presented and improved tools
   overall; loudness normalization (LUFS profiles + loudness strip per
   collection, like Sound Effects); audio/video fades; thumbnails/poster per clip
   and filmstrip timeline in the editor; test playback on a chosen
   `media_player` (never touching projector/screen).
5. **New product in parallel** with its own repo and domain; old
   `cinema_collections` stays installed until cut-over. HACS allows one
   integration per repo, hence a new repo.
6. **Approach A:** new repo bootstrapped from the Sound Effects skeleton,
   porting the proven video engine from Clips. Rejected: B (shared package for
   both products — too much upfront work, couples releases, forces refactor of
   production Sound Effects); C (inside hass-clips-manager — conflicts with HACS
   one-integration rule and parallel install).
7. Proposed names (user agreed to approach; confirm names at spec review):
   repo `hass-cinema-studio` (GitHub org `NaturalDevCR`), App "Cinema Studio",
   integration domain `cinema_studio`.

## What to take from each repo

From hass-sound-effects: App with Supervisor discovery (no manual bearer
secret), immutable publishing with retired-file acknowledgement, integration
that caches the catalog and selects without network (Studio can be offline),
native seasons + override select, persistent selection history, UI system
(NavBar, Sheet, ConfirmDialog, Toast, Icon, en/es translations, editor with
preview, audition on real targets), contract tests. Spec/plan:
`docs/superpowers/specs/2026-10-03-sound-effects-design.md`,
`docs/superpowers/plans/2026-10-03-sound-effects.md`.

From hass-clips-manager: ffprobe, FFmpeg compilation with lead/tail black
margins and timing metadata (`duration`, `content_duration`,
`lead_in_duration`, `tail_out_duration`, `content_start_offset`,
`content_end_offset`), job queue with idempotency, Cast compatibility profiles,
trim/crop edit jobs, playback modes and history. Specs under
`docs/superpowers/specs/` (cinema-collections, visual-playback-order,
clip-editing, cast-blackout-margins).

## Findings from review

- Clips pairing is manual (`bearer_secret`); Sound Effects uses discovery.
- Clips `select_next_clip` calls the Worker live (`ClipAvailabilityClient`):
  Worker down = cinema cannot start. Sound Effects selects from a local cache.
- Two sources of truth disagree today: `sensor.active_collection` = `halloween`
  (Worker schedule) while `sensor.temporada_de_cine_activa` = `regular`; the
  script follows the latter. Native seasons remove this.
- `script.cinema_reproducir` still calls `shell_command.cinema_clip_metadata`
  to confirm timing although the service already returns it — the new
  selection response must be trustworthy enough to retire that shell command.
- Production data: collections `regular` and `halloween`, 45 clips (44 ready,
  1 stale). Compiled media lives under `/media`; Cast plays a
  `media-source://` URI. Video stays in `/media` (not `/config/www`).

## Production constraints (bar Otocuma)

`script.cinema_reproducir` is a delicate flow: session guard
(`input_text.cinema_sesion`), standby black on `media_player.bar_otocuma_gc`,
screen `cover.ocl_screen_projector`, projector `media_player.otocuma_dp`,
A/V mute shell commands (`cinema_av_prepare/show/finish/release`), Snapcast
mutes, lights coordination, timing-based early close. Also
`automation.pre_compile_cinema_clips` (03:00 `cinema_collections.compile_all`).
Rules: never change playback/projector/A-V steps; migrate by copying the script
to a `_v2` and switching with an explicit rollback, each flow approved by the
user. The new selection response must stay compatible with the fields the
script reads (`media_content_id`, `clip_id`, `title`/`source_name`,
`relative_output_path`, `duration_seconds`, timing fields).

## Phases (approved outline)

1. Skeleton: App + discovery pairing, import from the old Worker (clips,
   collections, order, history), cached catalog and selection service with a
   response compatible with today's.
2. UI: Library, Organize (collections, seasons, profiles), System, Import.
3. Editor: trim/crop, fades, loudness, filmstrip, test on device.
4. Migrate `script.cinema_reproducir` (copy `_v2`, switch, rollback); retire
   `shell_command.cinema_clip_metadata`.
5. Uninstall the old product.

## Next steps (brainstorming skill, continue from here)

1. Ask GPT-6.1-Sol to critique this approach before writing the spec, focusing
   on offline video cache/selection and the contract with the projector script:
   `codex exec -m gpt-6.1-sol`. User delegation preference: Sol for hard
   tasks/design debate, GPT-6-Luna (`-m gpt-6-luna`) or Sonnet subagents for
   focused tasks.
2. Present design sections for approval (architecture, components, data flow,
   error handling, testing).
3. Write spec to `docs/superpowers/specs/2026-10-05-cinema-studio-design.md`,
   self-review, commit, ask user to review.
4. Invoke writing-plans.

User communicates in Spanish.
