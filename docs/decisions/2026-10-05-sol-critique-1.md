The approved architecture is sound, but Phase 1 needs a stronger publication and retention contract before its selection response can safely replace the metadata shell command. No files were modified.

**(a) Prioritized risks and recommendations**

1. **Critical: catalog caching does not guarantee playable bytes.** Sound Effects persists validated snapshots and retains them during connection failures ([coordinator.py](/Users/jdavidoa91/Dev/hass-sound-effects/custom_components/sound_effects/coordinator.py:53)); its selection path performs no file checks ([manager.py](/Users/jdavidoa91/Dev/hass-sound-effects/custom_components/sound_effects/manager.py:163)). For video, persist the complete selection catalog: collection membership/order/modes, seasons, enabled state, and immutable render records containing path, render identity, size/hash, profile identity, and timing.

   Validate local `/media` availability on startup and cheaply stat the selected file in an executor before committing history. Missing or mismatched files must be excluded. Hash once during publication/import and on suspicious changes, rather than hashing large videos per selection. Stat checks cannot prove byte identity; the guarantee depends on exclusive ownership and immutable outputs.

2. **Critical: port the compiler, but replace its publication identity.** Current jobs publish to the clip’s existing output path, then update database timing ([jobs.py](/Users/jdavidoa91/Dev/hass-clips-manager/app/src/cinema_collections_worker/jobs.py:1051)). Atomic replacement prevents partial files, but permits cached metadata to describe yesterday’s bytes at today’s path.

   Use unique, never-reused render paths. Validate/hash the completed staging file, publish it, then transactionally commit its manifest and catalog revision. A crash before catalog commit leaves an orphan to reconcile; a failed recompile preserves the prior publication. Separate *desired recipe status* from *published render validity*. Current selection prefers ready clips and only falls back to stale outputs when none are ready ([selection.py](/Users/jdavidoa91/Dev/hass-clips-manager/custom_components/cinema_collections/selection.py:132)); explicitly decide whether to preserve that policy, because it changes ordered sequences.

3. **Critical: retirement acknowledgement is insufficient for active playback.** Sound Effects uses persisted-catalog acknowledgement plus seven days’ grace ([design.md](/Users/jdavidoa91/Dev/hass-sound-effects/docs/superpowers/specs/2026-10-03-sound-effects-design.md:103)). Video adds long playback and delayed/repeated Cast requests.

   GC must require both removal from every supported consumer’s durable snapshot and expiry of selection protection. Define a bounded selection-to-playback window and maximum playback lifetime, then enforce a conservative retirement grace covering both; alternatively implement durable leases coordinated without requiring App reachability. Pin snapshot adoption and selection under one lock. Never acknowledge an unpersisted snapshot. Under disk pressure, reject new renders rather than delete protected files.

   App down or old catalog: continue using verified publications, exposing connectivity and age separately. HA restart: restore snapshot/history/protection before enabling selection. No valid snapshot: fail clearly. Define backup-restore handling so an older restored snapshot cannot revive already-collected paths.

4. **High: timing metadata is a media timeline, not a Cast startup clock.** The compiler probes final output but derives boundaries from frame-aligned margins ([jobs.py](/Users/jdavidoa91/Dev/hass-clips-manager/app/src/cinema_collections_worker/jobs.py:1120)). Verify those boundaries against encoded fixtures, including intro/outro, fades, LUFS processing, encoder delay and A/V synchronization. Keep content fades inside the content region and blackout margins black/silent.

   Preserve Cast profile validation and test actual target playback. Neither ffprobe nor a hash guarantees Cast startup latency. Confirm the existing script’s timing anchor; if it assumes playback starts when the service call returns, metadata alone cannot fix that within the approved “unchanged device steps” constraint.

5. **High: season-keyed history does not implement season-entry resets.** Sound Effects retains bags by season ([selection.py](/Users/jdavidoa91/Dev/hass-sound-effects/custom_components/sound_effects/selection.py:57)). Persist an activation identity covering calendar occurrence/year and manual transitions, plus ordered progress; restart within the same activation resumes, while re-entry resets ordered modes once. Reconcile transitions missed while HA was down.

   Define action-only overrides separately, empty-season fallback explicitly, and deletion/reordering behavior. Preserve history by logical clip ID across recompiles. Reconcile random eligibility without clearing already-selected IDs. Retain durable claims: cinema saves before returning ([history.py](/Users/jdavidoa91/Dev/hass-clips-manager/custom_components/cinema_collections/history.py:163)); Sound Effects delays saving by one second ([manager.py](/Users/jdavidoa91/Dev/hass-sound-effects/custom_components/sound_effects/manager.py:286)).

**(b) Proposed response contract**

Keep the script’s flat fields, adding:

- `contract_version`, `instance_id`, `catalog_revision`, `render_id`, `profile_fingerprint`.
- `selection_id`, `selected_at`, protection deadline.
- `collection_id`, requested/effective season, season source/fallback, playback mode, `history_reset`.
- `clip_id`, `title`, `source_name`, `relative_output_path`, `media_content_id`, `media_content_type`.
- `duration_seconds`, `duration`, and all six existing timing fields; render size/hash and explicit stale-render status.

Guarantee that path, identity and timing describe **one immutable publication**. `duration_seconds == duration`; finite seconds; `0 ≤ start < end ≤ duration`; content duration equals end−start, lead equals start, tail equals duration−end within a documented frame/sample tolerance. Preserve fractional values; optionally store canonical integer time units internally. Unknown timing must fail projector selection, never silently invent zero margins. Version schema separately from catalog/render revisions; incompatible versions fail before device actions.

**(c) Phase changes**

Expand Phase 1 with publication/GC, native season semantics, integration-history import, crash recovery and offline-restart tests. History cannot come solely from the Worker.

Use separate `/media` output namespaces and copied originals: current editing can replace sources ([jobs.py](/Users/jdavidoa91/Dev/hass-clips-manager/app/src/cinema_collections_worker/jobs.py:660)). Import a consistent snapshot with stable-ID mapping and a reconciliation report.

Prepare `_v2` early for dry-run comparisons; migrate after editor processing passes timing tests. Keep device steps unchanged. Cut-over must switch callers, season/reset authority and the 03:00 compile automation together. Retain old files/configuration and metadata fallback throughout rollback observation; uninstall last.

**(d) Open questions**

- Maximum selection delay/playback duration and acceptable retained-video storage?
- Empty season: regular fallback or stop?
- Manual season re-entry and per-call overrides: which reset ordered progress?
- Does the production script anchor timing to observed Cast playback?
- Can migration duplicate originals/renders, and where is the authoritative integration-history export?
