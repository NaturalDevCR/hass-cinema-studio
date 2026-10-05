# Cinema Studio for Home Assistant

Cinema Studio is a Supervisor App for importing, editing, rendering and organizing cinema video clips, paired with a HACS integration (`cinema_studio`) that picks the next clip to play by season and collection and returns a verified, playable media URI with measured timing. Home Assistant automations stay in control of playback and devices, so the App can be stopped, updating or crashed and selection keeps working from the integration's cached catalog.

## Features

- **Import from Cinema Collections.** One action (`cinema_studio.import_legacy`) imports clips, collections, processing profiles, seasons, playback history and the exact files that play today, reusing hard links when possible so no extra disk space is needed.
- **Editor.** Trim, crop, fade in/out, loudness normalization (LUFS profiles) and gain, with poster and filmstrip timeline, preview render and **test on a device** (a `media_player` you choose).
- **Seasons and collections.** Date-ranged seasons (yearly `MM-DD`, wrapping New Year, priorities) map to collections with `random` (no-repeat rounds), `sequential` or `custom` playback order. A season override select and an optional season entity are available.
- **Offline-safe selection.** The integration keeps a persisted catalog snapshot, verifies each render file on disk (existence, containment, size) and selects without calling the App.
- **Trustworthy response.** Every selection describes one immutable render that passed timing and file checks within that call; unknown timing is never returned.
- **Immutable renders and garbage collection.** Each publish creates a new, never-reused file. Old renders are removed only after a shared filesystem fence confirms that no consumer still holds or has pinned them.
- **Phone-friendly UI.** Library, Upload, Organize, Editor and System views in English and Spanish.

## How it works

```text
Cinema Studio App renders immutable MP4s into /media/cinema-studio/renders/<clip_id>/
        -> the integration caches the catalog, verifies files and selects without network access
        -> your automation or script plays the returned media-source URI
```

The App owns originals, recipes, renders, collections, seasons and profiles. The integration owns the catalog snapshot, file verification, season resolution and selection history. Automations own playback.

<!-- screenshots -->

## Installation summary

Requires Home Assistant **2025.12.0 or newer** (Supervisor installation: Home Assistant OS or Supervised).

1. In Home Assistant, open **Settings > Apps > App store > menu > Repositories** and add `https://github.com/NaturalDevCR/hass-cinema-studio`.
2. Install and start **Cinema Studio** from the App store.
3. In HACS, add `NaturalDevCR/hass-cinema-studio` as a custom repository of category **Integration**, download **Cinema Studio**, and restart Home Assistant.
4. Confirm the discovered **Cinema Studio** card in **Settings > Devices & services**. See [Installation](docs/installation.md) for manual setup.

## Connecting

The App announces itself through Supervisor discovery with its address and API token; accepting the discovery card creates the integration entry (a single instance is allowed). If discovery does not appear, restart the App once, or add the integration manually with the App's hostname (shown on its Supervisor App page), port `8099` and the API token from **System > Connection**. The sensor `binary_sensor.cinema_studio_studio_connected` shows whether the App is reachable. Selection does not depend on it.

## Selecting the next clip

`cinema_studio.select_next_clip` chooses the next clip and returns data for your own playback action. It does not play anything.

| Field | Required | Description |
| --- | --- | --- |
| `collection_id` | No | Collection ID or name. Bypasses the season-to-collection mapping. |
| `season` | No | Season ID or name for this call only. |
| `dry_run` | No | Defaults to `false`. Returns a pick without recording history or changing season activation. |

```yaml
actions:
  - action: cinema_studio.select_next_clip
    response_variable: clip
  - action: media_player.play_media
    target:
      entity_id: media_player.cinema_projector_cast
    data:
      media_content_id: "{{ clip.media_content_id }}"
      media_content_type: "{{ clip.media_content_type }}"
  - delay:
      seconds: "{{ clip.duration }}"
```

Main response fields (the complete contract is in [Automations](docs/automations.md)):

| Field | Meaning |
| --- | --- |
| `contract_version` | Always `1`. Reject any other value. |
| `clip_id`, `title` | Selected clip. |
| `media_content_id` | `media-source://` URI of the immutable render. It contains the `clip_id`. |
| `media_content_type` | Always `video`. |
| `duration` | Total file duration in seconds (`duration_seconds` is identical). |
| `content_start_offset`, `content_end_offset` | Where the clip content begins and ends inside the file, in seconds. |
| `lead_in_duration`, `tail_out_duration` | Black/silent margins before and after the content. |
| `timing_verified`, `file_verified` | Always `true` in a returned response. |
| `season`, `collection_id`, `season_fallback` | What was resolved and whether the Regular fallback was used. |
| `history_reset` | `true` when a new playback round started. |

If nothing can be played the action raises a validation error (`not_ready`, `no_playable_clip`, `unknown_collection`, `unknown_season`). Use `continue_on_error: true` when you have a fallback path.

## Import from Cinema Collections

If you already run the Cinema Collections Worker App and its `cinema_collections` integration, run the action `cinema_studio.import_legacy` from **Developer tools > Actions**. It reads the old integration's stored connection (you never handle its credentials), imports clips with their ids, original files and compiled outputs as render `r1` (with the exact timing the old product used), collections with mode and order, processing profiles and seasons, then imports playback history. It is idempotent and never stops or changes the old product. Run it while the old Worker is idle. Pass `history_only: true` to refresh only the history. The result is also shown as a notification and in **System > Legacy import**. See the [migration guide](docs/migration.md) for a safe production cut-over.

## Guía rápida (español)

1. En Home Assistant, vaya a **Ajustes > Apps > Tienda de Apps > menú > Repositorios** y agregue `https://github.com/NaturalDevCR/hass-cinema-studio`. Instale e inicie **Cinema Studio**.
2. En HACS, agregue `NaturalDevCR/hass-cinema-studio` como repositorio personalizado de categoría **Integración**, descargue **Cinema Studio** y reinicie Home Assistant.
3. Acepte la tarjeta de descubrimiento en **Ajustes > Dispositivos y servicios**. Si no aparece, reinicie la App una vez, o agregue la integración manualmente con el nombre de host de la App (en su página de Supervisor), el puerto `8099` y el token de **Sistema > Conexión**.
4. Abra el panel **Cinema Studio**: cargue clips en **Subir**, agrúpelos en colecciones y temporadas en **Organizar** y edítelos (recorte, encuadre, fundidos, volumen) desde la **Biblioteca**.
5. Use la acción `cinema_studio.select_next_clip` con `response_variable` y reproduzca `media_content_id` con `media_player.play_media`. Antes de una migración real, revise la [guía de migración](docs/migration.md) y el [plan de reversión](docs/ROLLBACK.md); si ya usa Cinema Collections, importe con `cinema_studio.import_legacy`.

## Documentation

- [Installation](docs/installation.md)
- [Usage](docs/usage.md)
- [Automations](docs/automations.md)
- [Migration from Cinema Collections](docs/migration.md)
- [Rollback](docs/ROLLBACK.md)

## License

Apache-2.0. See [LICENSE](LICENSE).
