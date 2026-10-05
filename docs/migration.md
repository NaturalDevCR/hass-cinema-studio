# Migration from Cinema Collections

This guide moves a running system from the Cinema Collections Worker App (`cinema_collections` integration) to Cinema Studio with a one-step rollback at every stage. The old product is never stopped or changed during the migration, and nothing in your device steps (projector, screen, audio/video, lighting) is edited.

The steps assume a playback script that today calls `cinema_collections.select_next_clip` and a metadata step before it starts any device. Names such as `script.cinema_reproducir` or `shell_command.cinema_clip_metadata` are examples; substitute your own. See [Rollback](ROLLBACK.md) for how to undo each step.

## How the migration protects you

- The old App and integration keep running and stay the fallback.
- The new selection path is validated on every call (see [Automations](automations.md)); anything invalid or failing falls back to the old steps, verbatim.
- Only the selection and metadata steps of your script change, and they are tested first in a copy that stops before any device step.
- Rolling back is restoring one script from a backup copy.

## Pre-flight

1. Create a full Home Assistant backup. Include the Media folder if you can; originals are hard-linked, not copied, so they remain in the old product's folders either way.
2. Pick a quiet time: no cinema session running (your phase helper in rest state, playback script off), outside the hours when sessions are scheduled, and outside the old product's nightly compile window (the import refuses to start while the old Worker is busy and should not run during 03:00-03:30).
3. Check that the old Worker is idle (no queued or active jobs).
4. Make sure the old product works: it must remain your fallback.

## Step 1: Install and connect

1. Add the App repository `https://github.com/NaturalDevCR/hass-cinema-studio`, install and start **Cinema Studio**.
2. In HACS add `NaturalDevCR/hass-cinema-studio` (category **Integration**), download it, run a configuration check and restart Home Assistant.
3. Accept the discovered **Cinema Studio** entry. See [Installation](installation.md).
4. In the integration options set **Season entity** to the entity that your current script follows to choose the season (the helper or sensor that drives it today), so both paths agree.
5. Confirm `binary_sensor.cinema_studio_studio_connected` is on.

## Step 2: Import

Run `cinema_studio.import_legacy` (leave `history_only` off) from **Developer tools > Actions**. The integration reads the old integration's stored connection itself. It:

- stages every original and compiled output in a private folder (hard links when on the same filesystem, otherwise copies) and checks them against the old Worker's recorded fingerprints and timing;
- re-fetches the Worker data and drops any clip that changed meanwhile (re-run to pick those up);
- then publishes each accepted clip as render `r1` with the old product's exact bytes and timing, keeping clip IDs, collection IDs, modes, custom order and titles, and creates the seasons Regular, Halloween and Christmas when their date helpers exist;
- imports playback history.

Read the report (the notification, or **System > Legacy import** in the App). Every ready clip should be in `imported`. Review anything in `skipped` (stale without output, missing files), `queued_for_render` (the output failed checks but the source is fine; a new render is made with the profile's standard margins), `needs_source` (the output is usable but editing is disabled until you re-upload the source) and `missing_assets`. Intro or outro files used by the old profile cannot be read from the old product; imported renders already contain them, but a **new** render with that profile is blocked until you upload the asset in **Organize**. Investigate any rejection before continuing. Re-running imports nothing that is already imported.

## Step 3: Parity check by manifest

Compare data, not random picks:

1. For every clip ID, compare the new catalog render (duration, content start/end, lead-in, tail-out, title) with the old Worker values.
2. For a sample of at least 5 clips per collection (include any clip that was stale), compare with the old metadata step's output.
3. Compare collection mode and order.
4. For ordered (`sequential` or `custom`) collections, call both services with `dry_run: true` and confirm that they return the same clip ID.

Random collections cannot be compared by picks, so compare manifests only.

## Step 4: Self-test script

Create a test script containing a copy of the entire replacement block, as it will appear in the production script: the new selection, validation, variable mapping and fallback. Differences from production:

- both services are called with `dry_run: true`;
- it stops before any device step and returns the resulting variables as a script response (`stop` with `response_variable`);
- it writes no helper and never calls your logging or registration script;
- it has two test fields, `force_fallback` and `force_invalid_contract`. `force_fallback` makes the new-path call fail (for example, by selecting an unknown collection), and `force_invalid_contract` corrupts one field of the response before validation.

Run it three ways and check that each returns valid variables (clip ID, URI, title, duration, content start/end, lead-in, tail-out):

1. normal (new path);
2. `force_fallback: true` (fallback path);
3. `force_invalid_contract: true` (validation fails, fallback path).

The pattern in [Automations](automations.md#fallback-pattern) is the block to test.

## Step 5: Backup, cut-over and in-place edit

1. Run `cinema_studio.import_legacy` with `history_only: true` immediately before the cut-over so the new path continues where the old one stopped.
2. Create the rollback copy: a script that is an exact copy of your current production script, named for example `script.cinema_reproducir_v1_backup`. Never call it. Also keep a copy of the YAML outside Home Assistant.
3. Edit the production script in place:
   - initialize the selection variable to `{}`;
   - replace **only** the old selection and metadata steps with the block proven by the self-test (without `dry_run`), at the same position, before any device action;
   - new path: `cinema_studio.select_next_clip` with `continue_on_error: true` and `response_variable`, then full validation (`contract_version == 1`, `timing_verified`, `file_verified`, clip ID and URI non-empty, URI contains the clip ID, timing finite and consistent). If valid, map duration, content start/end, lead-in, tail-out and clip name from the response;
   - invalid or error: the old selection and metadata steps, verbatim, plus a log entry so fallbacks are counted;
   - diff every other step against the backup. They must be identical. Record a hash of both configurations.
4. Run the production script once while no session is active, if your setup lets you do so safely; otherwise wait for the first scheduled session and watch it.

## Step 6: Observation

During observation keep enabled:

- the old App and old integration (they are the fallback);
- the old nightly compile automation (it keeps the fallback Worker current); the new App needs no nightly compile because it renders on every recipe change;
- the old automation that resets history when the season changes (the fallback path keeps its own correct history).

Watch each session result and count fallback events. Known trade-off: the two histories are independent, so a session that falls back may repeat a clip that Cinema Studio already played. This is rare.

## Exit gate

You decide when the migration is done. A reasonable gate is at least 20 sessions over at least 7 days, with a completion rate no worse than the previous 7 days and **zero** fallback events. Only after that, and in your own time, you can:

1. switch to native seasons (clear the **Season entity** option and manage seasons in **Organize**);
2. disable the old season-change reset automation and the old nightly compile automation;
3. remove the fallback block from the script;
4. uninstall the old product.

Until then, rollback is always available; see [Rollback](ROLLBACK.md).
