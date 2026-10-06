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

## Incident 2026-10-05 21:15–23:51 CST — 4K re-render OOM (fixed in v0.1.1)

- Trigger: intro asset upload re-rendered 41 clips (`4k-loudness-with-intro`). 5 renders failed
  (it-lepper-scene, angry-birds-1, avengers-trimm, back-to-the-future-1-1, it-projector-scene);
  UI showed the tail of an earlier successful ffmpeg log instead of the cause. App container
  reached 9.6 GB of the 12.5 GB VM. Playback unaffected (published renders kept, 45/45 playable).
- 22:50 App stopped as a safety measure. Root cause reproduced in Docker: single demuxer per
  file let audio demand decode 4K video that queued before xfade (ffmpeg 6.1: 7.2 GB, OOM 137).
- v0.1.1 (Sol: approve with changes → SHIP): split video/audio inputs, `encoder_threads` option
  (default 4), FFmpeg 8.1 (alpine3.24), oom_score_adj 1000 on media children, real failure
  messages, restart re-queues pending renders, thumbnails first, UI fixes. Real add-on image:
  2.67 GB peak, −18.02 LUFS, −1.95 dBTP.
- 23:23 backup `403afc95` (pre-0.1.1). Updated App, started: 45 thumbs + 28 renders re-queued.
  First render (jurassic-park-3) done in 12.5 min, container 2.3–2.5 GB. 23:51 the 5 failed
  clips re-queued once by hand.
- Rollback: stop App, restore `403afc95` App partial or reinstall v0.1.0.
