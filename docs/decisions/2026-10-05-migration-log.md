# Production migration log — 2026-10-05

- 13:11 Pre-A backup `83c82f79` (pre-cinema-studio-2026-10-05).
- 16:26 v0.1.0 released; App `a5c73b0d_cinema_studio` installed/started; HACS v0.1.0 downloaded.
- ~21:08 User restarted HA (bar empty, user present). Old integration loaded, cinema idle.
- 21:10 `input_boolean.cinema_mantenimiento` ON (was off).
- User confirmed discovered Cinema Studio flow in the UI. Options: season_entity = sensor.temporada_de_cine_activa.
- 21:11 `cinema_studio.import_legacy`: 45/45 imported, 0 skipped, 0 needs_source, 0 queued; missing asset treebu-hotels-intro.mp4 (expected). Catalog revision 53, consumer fence file present.
- Parity: 11 clips (5 regular + 5 halloween + titanic trace) match `shell_command.cinema_clip_metadata` to the millisecond.
- 21:13 `script.cinema_studio_selftest` created; normal / forced fallback / invalid contract all valid. media_source resolve of new URI OK (video/mp4).
- 21:13 `import_legacy history_only`; machine backup `script.script.cinema_reproducir.20261006_031347.yaml`; `script.cinema_reproducir_v1_backup` created.
- 21:15 `script.cinema_reproducir` edited in place (hash ba04f0a1717e29c0 → 50f4298a962c540f): steps 5–10 replaced by the approved block; steps 0–4 and 9+ verified unchanged. Selftest re-run OK.
- 21:16 Maintenance restored to off. Real test session (user present): new path selected pirates-of-the-caribbean (cinema-studio render r1), Cast duration 219.4 = catalog 219.4, `resultado = completado` at 21:20:36, projector off, screen retracting. User: "worked great".

Rollback: restore `script.cinema_reproducir` from `script.cinema_reproducir_v1_backup` or `ha_manage_backup edits restore script.script.cinema_reproducir.20261006_031347.yaml` (maintenance ON → idle → restore → verify → maintenance back).
Observation gate before removing the old product: ≥ 20 sessions and ≥ 7 days, zero `respaldo_seleccion` events.
