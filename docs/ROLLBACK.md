# Rollback

Rolling back is always possible and quick, because the old product (the Cinema Collections App and `cinema_collections` integration) is never stopped, changed or uninstalled during the migration. The only change to production behavior is the selection block in your playback script, and an exact copy of the original script is kept.

The names below follow the reference production setup: the playback script is `script.cinema_reproducir` and its backup is `script.cinema_reproducir_v1_backup`. Replace them with your own script names.

## One-step rollback (any time after the in-place edit)

Restore the playback script from its backup:

1. Open `script.cinema_reproducir_v1_backup` in **Settings > Automations & scenes > Scripts** and switch to **Edit in YAML**. Copy the whole YAML.
2. Open `script.cinema_reproducir`, switch to **Edit in YAML**, replace its content with the copy, and save. (If you manage scripts through the Home Assistant API or an automation tool, read the backup's configuration and write it to the original script ID in one call.)
3. Use the backup made in Step 5 of the migration; it matches the original production script exactly.

Nothing else needs undoing. Playback uses the old selection and metadata steps again, with the old product's own history. You can keep Cinema Studio installed and idle.

## Rollback per migration step

| Stage reached | What changed | How to roll back |
| --- | --- | --- |
| Pre-flight | Only a Home Assistant backup was created. | Nothing to undo. |
| Step 1: install and connect | The App and integration were installed and configured, and the **Season entity** option was set. | Production behavior is unchanged, since no script uses the new integration yet. To remove it: delete the integration entry (**Settings > Devices & services > Cinema Studio > Delete**), uninstall the HACS integration and the App, then restart Home Assistant. See "Removing Cinema Studio" below. |
| Step 2: import | Files were hard-linked or copied into `/media/cinema-studio/`, and a catalog and history were created in the new App and integration. The old product's files, database and history were not modified. | Nothing to undo for production. To start over, remove Cinema Studio as below. Hard links share storage with the old files, so deleting the new names never deletes the old product's files. |
| Step 3: parity check | Read-only comparison (and `dry_run` calls, which change nothing). | Nothing to undo. |
| Step 4: self-test script | A test script was created. It writes no helpers and calls no device. | Delete the test script. |
| Step 5: in-place edit | The playback script's selection and metadata steps were replaced. A backup copy and an optional history refresh were done. | Restore the script from `script.cinema_reproducir_v1_backup` (one-step rollback above). The history refresh only changed the new integration's own history. |
| Step 6: observation | Nothing else; the old product, its compile automation and its season-reset automation stayed enabled. | Same one-step rollback. If you already disabled the old compile or season-reset automation after the exit gate, re-enable them before restoring the script. |
| After the exit gate | Native seasons, old automations disabled, fallback removed or the old product uninstalled (your decision). | Restore the script from the backup, re-enable the old automations and, if you uninstalled the old product, reinstall it and its Worker data from a Home Assistant backup first. |

## Removing Cinema Studio

Only when you want it gone and after the script no longer calls it:

1. Restore the playback script (above) so nothing calls `cinema_studio.*`.
2. **Settings > Devices & services > Cinema Studio > Delete.** This removes the integration's cached catalog and history from Home Assistant storage.
3. Uninstall the HACS integration, restart Home Assistant, and uninstall the **Cinema Studio** App.
4. Optional: delete the `/media/cinema-studio/` folder. Imported files are hard links of the old product's files when both are on the same filesystem; deleting this folder does not delete the old product's files. Check the old product's clips still play before deleting anything.

Do not delete `/media/cinema-studio/` while a script may still call the new path.

## Last resort: restore a Home Assistant backup

If something unexpected is wrong with Home Assistant itself, restore the full backup created in the pre-flight step from **Settings > System > Backups**. This returns configuration, scripts and App data to that point in time, so any session history, helper values and edits made after the backup are lost. Prefer the one-step script rollback; use the backup only when that is not enough.

After a restore, Cinema Studio recovers by itself: the integration re-declares the renders its restored catalog holds before it selects anything, renders that no longer exist fail the file check and are not played, and the App never deletes a render that a consumer still holds or has pinned.

## If Home Assistant Core does not start after the restart

A failing custom integration does not stop Core from starting (Home Assistant isolates
integration setup errors), and the configuration check runs before the restart. If Core
still does not come back within ~10 minutes, recovery has to go through the Supervisor,
because every tool that talks to Home Assistant goes through Core:

1. Open the Home Assistant OS console (keyboard/monitor on the VM, or the hypervisor
   console) or the Supervisor Observer page at `http://<ha-host>:4357`.
2. Restore the pre-migration backup **`pre-cinema-studio-2026-10-05`** (id `83c82f79`),
   taken before the integration was downloaded, so it contains no `cinema_studio` files:

   ```bash
   ha backups restore 83c82f79
   ```

   The backup is protected with your default backup password (Settings → System →
   Backups → encryption key / emergency kit).
3. Core restarts with the configuration exactly as it was before the migration.
