# Production migration plan — Cinema Studio (draft for Sol consensus)

Context at 2026-10-05 13:05 CST: bar OPEN (`input_boolean.bar_cerrado_otocuma` off since
11:04). Cinema window 17:30–22:00 (`input_datetime.cinema_clips_hora_inicio/fin`), sessions
launched by `automation.cine_aleatorio_cada_30_min` → `automation.cinema_clips_mode` →
`script.cinema_sesion` → `script.cinema_reproducir`. Session gates include
`input_boolean.cinema_mantenimiento` (off) and `input_select.cinema_fase == reposo`.
HA OS 18.3, Core 2026.10.0b0, amd64 VM. Old: App `6f478b37_cinema_collections_worker` 1.11.0,
integration `cinema_collections` 2.3.0 (entry `01M148A20582RA0Z190G7J4RAY`).

## Phase A — non-disruptive (now, bar open is fine)

A0. Snapshot: `ha_manage_backup(scope=snapshot, action=create, name="pre-cinema-studio-2026-10-05")`
    (no DB). Verify with `snapshot list`: completed, id recorded, includes homeassistant
    config (scripts/automations) and the old Worker App data. Restore handle = backup id
    (Settings → System → Backups or `ha_manage_backup snapshot restore`). A fresh backup is
    taken again right before Phase B.
A1. Publish repo `NaturalDevCR/hass-cinema-studio` (public) + tag `v0.1.0` after CI green.
A2. `ha_manage_app(add_repository, https://github.com/NaturalDevCR/hass-cinema-studio)`;
    install `*_cinema_studio`; start; check logs (no HA restart needed). App only reads/writes
    `/media/cinema-studio/`; it cannot touch the old Worker or production scripts.
A3. `ha_manage_hacs(add_repository NaturalDevCR/hass-cinema-studio, integration)` + download
    v0.1.0. Files land in `/config/custom_components/cinema_studio`; inert until restart.

Rollback for A: uninstall App, remove HACS repo; nothing in production references them.

## Phase B — needs one HA restart (ONLY after the bar is closed tonight)

B0. Preconditions (ALL): `input_boolean.bar_cerrado_otocuma` on, `input_select.cinema_fase ==
    reposo`, scripts `cinema_reproducir`, `cinema_sesion`, `cinema_streaming_iniciar`,
    `cinema_abortar`, `cinema_proyector_apagar`, `cinema_clips_cleanup` off,
    `input_boolean.streaming_mode_status` off. Record the current value of
    `input_boolean.cinema_mantenimiento`, then turn it ON for the whole of B–D (it gates
    `automation.cine_aleatorio_cada_30_min` and `script.cinema_sesion`; it is a restored
    input_boolean so it survives restart — verify after restart). Fresh snapshot backup.
B1. `ha_get_system_health(include=config_check)` valid → `ha_restart`.
B1a. Post-restart gate (max 10 min): Core responding; `cinema_collections` entry loaded and
    `sensor.active_collection` available; old Worker App started; media players
    (`media_player.bar_otocuma_gc`, Snapcast clients), lights coordination entities and
    `input_boolean.cinema_mantenimiento` == on.
    Core-down recovery: a custom integration's import/setup failure is isolated by HA and
    cannot stop Core from starting; YAML/config errors are excluded by the config check in
    B1. If Core still does not come back within 10 min, the MCP (which talks to Core) is
    unusable, so recovery is Core-independent and done by the user: restore the verified
    **pre-A** snapshot (taken before the HACS download, so it contains no cinema_studio
    files) from the Supervisor (HA OS console `ha backups restore <id>`, or the Observer page
    on port 4357). This route is documented in the morning report and docs/ROLLBACK.md.
B2. Accept the discovered `cinema_studio` flow (`ha_set_integration` / flow confirm); set
    options `season_entity = sensor.temporada_de_cine_activa`. Verify
    `binary_sensor.cinema_studio_studio_connected` on.

Rollback for B: remove the `cinema_studio` config entry; HACS remove; restart later.

## Phase C — import + verification (no production behaviour change)

C1. Old Worker idle by authoritative live status: the import service itself queries the
    Worker `/api/v1/status` and `/api/v1/jobs` (queued AND running) and refuses otherwise;
    not 03:00–03:30. Staged fingerprint + refetch validation are mandatory (built in).
    ANY unexpected rejection blocks cut-over (stop at Phase C, leave old path untouched).
    Call `cinema_studio.import_legacy` (`history_only: false`). Expect 44 imported (+1 stale
    handled per rules), 0 unsafe-path rejections. Investigate any rejection.
C2. Parity by manifest: for every clip compare new render timing/duration/name vs the old
    Worker data and `shell_command.cinema_clip_metadata` for ≥ 5 clips per collection.
C3. `script.cinema_studio_selftest` (fields `forzar_respaldo`, `forzar_contrato_invalido`):
    exact replacement block with `dry_run: true` on both services, stop with response
    variables. Run 3 ways; all valid.

## Phase D — cut-over (only if C fully green)

D1. `cinema_studio.import_legacy history_only: true`.
D2. Re-read `script.cinema_reproducir` immediately before editing (record config_hash) and
    create `script.cinema_reproducir_v1_backup` as an exact copy; verify the copy's config
    equals the original.
D3. Edit `script.cinema_reproducir` in place: replace only the selection + metadata steps
    (the `cinema_collections.select_next_clip` action, the variables block mapping it, the
    `shell_command.cinema_clip_metadata` call, the timing parse and its validation `if`)
    with the selftest-proven block (new service → validate → map; on error/invalid →
    old steps verbatim). Re-read the persisted config, diff every other step equal to the
    backup, run config check, rerun `script.cinema_studio_selftest` (3 modes) after the edit.
D4. Leave enabled: old App/integration, `automation.pre_compile_cinema_clips`,
    `automation.cinema_clips_reiniciar_historial_al_cambiar_de_temporada`.
D5. Restore `input_boolean.cinema_mantenimiento` to its recorded initial value.
D6. First real playback happens in the next normal session window (tomorrow 17:30+); the
    morning report tells the user what to watch; traces of `script.cinema_reproducir` show
    which path ran (`respaldo_seleccion` events = fallback).

Failure at any point in B–D: restore the old working path first (script from
`_v1_backup` if already edited), then restore the recorded maintenance value — never leave
cinema disabled silently.

Rollback for D (any time later), in this order: record the maintenance value → turn
`input_boolean.cinema_mantenimiento` ON → if a session is running, run `script.cinema_abortar`
→ wait until all cinema scripts are off and `cinema_fase == reposo` → replace
`script.cinema_reproducir` config with `_v1_backup` (one MCP call) → verify the persisted
config equals the backup → restore the recorded maintenance value.

## Observation exit gate (user decision)
≥ 20 sessions and ≥ 7 days, zero `respaldo_seleccion` events, `resultado == completado` rate
no worse than the previous 7 days. Old App/integration/automations stay installed and enabled
throughout; only then may the user disable/uninstall them.

## Timing (agreed with Sol, round 3)
Phase A now. Phases B–D are DEFERRED until the user confirms someone with HA OS console /
Supervisor access (and the backup encryption key, if any) is available during the restart
and recovery window, AND the bar is closed with cinema idle. Reason: the MCP reaches the
Supervisor only through Core, so an unattended Core-down recovery is impossible.
