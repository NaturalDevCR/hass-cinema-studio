Required changes:

1. **Restart after confirmed bar closure.** Replace B0’s “closed **OR** outside cinema hours” with **bar closed AND cinema idle**. Maintenance blocks cinema launches; it does not protect music, lighting or other HA-dependent operations from restart. Proceed with A now; defer B–D until closure. Do not assume the user can forgo tonight’s cinema. ([B0/open question](/Users/jdavidoa91/Dev/hass-cinema-studio/docs/decisions/2026-10-05-migration-plan.md:26))

2. **Make maintenance cover B–D and every exit path.** Record its initial value, enable it, then recheck all cinema entry scripts and recovery/streaming flows are idle. Verify maintenance survives restart and actually gates every launcher. On failure, restore the old working path before restoring the recorded maintenance value; never silently leave cinema disabled. ([B0](/Users/jdavidoa91/Dev/hass-cinema-studio/docs/decisions/2026-10-05-migration-plan.md:26), [D5](/Users/jdavidoa91/Dev/hass-cinema-studio/docs/decisions/2026-10-05-migration-plan.md:59))

3. **Verify the backup and restart recovery.** Record backup completion, contents and an accessible restore handle; explicitly confirm scripts/configuration and old App data are covered. Add a bounded post-restart gate checking Core, old integration/Worker and bar-critical services. Define recovery if Core fails to start; removing the new config entry is insufficient then. ([A0/B rollback](/Users/jdavidoa91/Dev/hass-cinema-studio/docs/decisions/2026-10-05-migration-plan.md:13))

4. **Use authoritative Worker readiness.** Check live Worker status for both queued and active jobs, rather than relying solely on `sensor.active_collection` attributes. Keep staged fingerprint/refetch validation mandatory. Any unexpected rejection blocks cut-over. ([C1](/Users/jdavidoa91/Dev/hass-cinema-studio/docs/decisions/2026-10-05-migration-plan.md:38))

5. **Gate cut-over and rollback against active playback.** Capture a fresh exact backup immediately before editing; config-check, verify the persisted diff and rerun the replacement-block selftest afterward. Rollback must enable maintenance and wait for idle—or use the existing abort flow—before editing. ([D2–rollback](/Users/jdavidoa91/Dev/hass-cinema-studio/docs/decisions/2026-10-05-migration-plan.md:50))

6. **Restore the observation gate.** Document ≥20 sessions/≥7 days, zero fallback events and completion-rate parity. Keep old dependencies throughout; first real playback occurs at the next authorized session window, with trace monitoring and rollback criteria.

CONSENSUS: NO
