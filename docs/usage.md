# Usage

The Cinema Studio App is a Home Assistant sidebar panel (Ingress) with five areas: Library, Upload, Organize, Editor and System. On phones the navigation sits at the bottom; on wider screens it is a sidebar. The interface is available in English and Spanish.

## Concepts

### Collections and playback modes

A collection is a group of clips with a playback mode and a processing profile:

- **Random:** picks uniformly from clips not yet played in the current round. When all have played, a new round starts (`history_reset: true`).
- **Sequential:** plays in a fixed order (the clip sort key), one per call, starting a new round at the first clip.
- **Custom:** plays in the order you set by dragging clips in the collection; clips not in that order follow in sort-key order.

History is stored per collection by the integration and persists across restarts. Reset modes (`on_exhaustion`, `daily`) are set in the integration options. The action `cinema_studio.reset_history` clears one collection or all.

### Seasons

A season has an ID, name, an optional yearly `MM-DD` start and end (inclusive, may wrap New Year), a priority and the collection that plays in it. **Regular** is built in, has no date range and is the fallback. When date ranges overlap, the higher priority wins.

The effective season is the first match of: the `season` field of the action, the season override select (when not `Auto`), the optional season entity, the calendar date, then Regular. If the season's collection is missing, empty or has no verified clips, Cinema Studio plays the Regular collection and reports `season_fallback: true`.

When the effective season changes (calendar, override select or season entity) and its collection is available, that collection's history restarts once so ordered playback begins at the first clip. A fallback does not reset anything. Selections with a per-call `season` or `collection_id`, and dry runs, never change season activation.

### Renders and verification

Every publish creates a new render file that is never reused or modified. The integration verifies that each published render exists inside `cinema-studio/renders/`, is a regular file and has the cataloged size, at startup, on each new catalog and again when selecting. A clip whose render fails verification is skipped. Edits you save show a **Render pending** badge until the new render is published; until then the previous render keeps playing (`render_pending: true` in the response).

## Views

### Library

Browse clips by collection (chips with counts), filter by season and status, and search. Each clip card shows its poster, duration, render status, loudness and any pending or source-needed badge. Select several clips for bulk actions: move to a collection, enable or disable, normalize to a profile, re-render or delete. In a `custom` collection, drag clips (or use the move up/down controls) to set the playback order. The loudness strip shows how even a collection's loudness is and can level it. The **Import from Cinema Collections** button points to the legacy import.

### Upload

Add clips by drag and drop or file picker. Files upload in 4 MB chunks with per-file progress. Choose the destination collection and processing profile for the batch. After upload the App probes the file, generates thumbnails and renders it with the collection's profile; progress shows in the job tray.

### Organize

- **Collections:** name, color, icon, playback mode, custom order and processing profile.
- **Seasons:** a yearly timeline with a date probe to check which season applies on a given day, plus each season's collection and priority.
- **Normalization profiles:** named loudness targets (LUFS, true peak, LRA).
- **Processing profiles:** the video and audio encode settings, scaling, loudness, clip fades and intro/outro with transitions used when rendering. Changing a profile re-renders the affected clips.
- **Assets:** intro and outro files. Assets that could not be carried over from an import show as missing; a new render that needs one is blocked until you upload the file.

### Editor

Open a clip from the Library. The editor offers:

- A player for the original, a preview render, or the published render.
- A filmstrip timeline with trim handles.
- A crop box overlay.
- Fade in and fade out (inside the content), gain, and a loudness profile override.
- Lead-in and tail-out margins (black and silent; default 2 s each, adjustable in System). Zero is a valid value.
- **Preview render:** renders a temporary file you can watch in the browser.
- **Test on device:** plays the preview or the published render on a `media_player` you configured in System.
- **Save & publish:** saves the recipe and queues a new render. The old render stays published until the new one passes timing validation.

If a render fails, the previous render stays published and the clip shows the ffmpeg error.

### System

- **Connection:** discovery status and the API token (reveal, copy, rotate). Rotating the token makes the integration ask you to reauthenticate.
- **Storage:** free space, originals, renders, retired renders and temporary work. New renders are refused when free space would fall below the disk reserve (default 2 GiB).
- **Garbage collection:** retired renders are deleted only when no consumer holds or has pinned them and they are at least 48 hours old. It halts when it cannot be sure (for example network storage or an unreadable consumer file) and shows why. You can run it manually.
- **Consumers:** integrations that have reported in, with the revision they hold and their pins.
- **Test devices:** the `media_player` entities used by **Test on device**, and a protected-entities list the App will refuse to play on (keep projectors, screens and other critical devices there). The App only calls `media_player.play_media` for devices on the test list.
- **Defaults and limits:** default margins, maximum upload size and duration, disk reserve.
- **Legacy import:** result of the last `cinema_studio.import_legacy` run (imported, queued for render, needs source, skipped, missing assets).

## Offline behavior

Selection uses the integration's persisted catalog and local file checks, so it keeps working while the App is stopped, updating or crashed. `binary_sensor.cinema_studio_studio_connected` turns off and edits are unavailable, but clips already published keep playing. Selection counters are queued and sent when the App returns. Selection is not available (`not_ready`) only before the first catalog, history and verification have loaded, or while the file-sharing lock with the App cannot be taken or is unreadable.

## Actions

| Action | Description |
| --- | --- |
| `cinema_studio.select_next_clip` | Select the next clip; see [Automations](automations.md). |
| `cinema_studio.reset_history` | Clear played clips for one collection (`collection_id`) or all. |
| `cinema_studio.refresh` | Fetch the latest catalog now and re-verify files. |
| `cinema_studio.import_legacy` | Import from Cinema Collections; see [Migration](migration.md). |

The integration fires the event `cinema_studio_selected` after each recorded selection, with the same data as the action response.
