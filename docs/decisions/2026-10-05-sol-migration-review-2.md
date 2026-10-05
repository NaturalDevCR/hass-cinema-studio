Three corrections remain:

- **Remove the duplicate restart.** B1 appears twice, before and after the post-restart gate. Delete the second occurrence so Phase B performs one restart. ([line 43](/Users/jdavidoa91/Dev/hass-cinema-studio/docs/decisions/2026-10-05-migration-plan.md:43))

- **Correct Core-down recovery.** The fresh pre-B snapshot is taken *after* HACS downloads the component, so restoring it does not remove those files. Use the verified pre-A snapshot for recovery, or explicitly remove/disable the new component through a Core-independent Supervisor/host route before restarting. Document a recovery route that remains callable while Core is unavailable. ([lines 35–42](/Users/jdavidoa91/Dev/hass-cinema-studio/docs/decisions/2026-10-05-migration-plan.md:35))

- **Maintenance must precede abort during rollback.** Replace “maintenance ON **or** abort” with: record maintenance state → enable maintenance → abort if necessary → wait for all cinema scripts idle and phase `reposo` → restore script → verify → restore maintenance. Otherwise another session can launch between abort and editing. ([line 87](/Users/jdavidoa91/Dev/hass-cinema-studio/docs/decisions/2026-10-05-migration-plan.md:87))

CONSENSUS: NO
