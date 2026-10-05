# Installation

Cinema Studio has two parts: the **Cinema Studio** Supervisor App and the **Cinema Studio** HACS integration (`cinema_studio`). Install both. The App edits and renders clips; the integration caches the catalog and selects clips.

Requires Home Assistant **2025.12.0 or newer** with Supervisor (Home Assistant OS or Supervised) and the default Media folder (`/media`, which Home Assistant exposes as the local media source).

## Install the Supervisor App

1. In Home Assistant, go to **Settings > Apps > App store**.
2. Open the menu, choose **Repositories**, and add `https://github.com/NaturalDevCR/hass-cinema-studio`.
3. Find **Cinema Studio** in the App store, install it, then start it.
4. Open **Cinema Studio** from the sidebar. On first start the App creates its API token and announces itself through Supervisor discovery.

The App maps the Media folder read/write and stores everything under `/media/cinema-studio/`:

| Path | Contents |
| --- | --- |
| `originals/<clip_id>/` | Uploaded or imported source files. Never modified. |
| `renders/<clip_id>/` | Published renders, one immutable file per render. |
| `assets/` | Intro and outro files used by processing profiles. |
| `consumers/` | Files written by the integration so the App knows which renders are still in use. |

## Install the HACS integration

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `NaturalDevCR/hass-cinema-studio` with category **Integration**.
3. Download **Cinema Studio** and restart Home Assistant.
4. Open **Settings > Devices & services** and confirm the discovered **Cinema Studio** card. If it does not appear, restart the App once so it announces itself again (the integration was not installed yet when the App first started).

Only one Cinema Studio instance is allowed. If Supervisor rediscovers the App, the existing entry's host and token are updated automatically.

## Manual setup

If discovery is unavailable, use **Settings > Devices & services > Add integration > Cinema Studio** and enter:

- **Host:** the App's hostname, shown on its Supervisor App page.
- **Port:** `8099`.
- **API token:** reveal or copy it in the App under **System > Connection**.

Use the App's hostname, not its Ingress URL. The integration checks the connection and token during setup.

## Options

Open the integration entry and choose **Configure**:

| Option | Default | Description |
| --- | --- | --- |
| Season entity | none | Optional `sensor`, `input_select`, `select` or `input_text` whose state is a season ID or name. Used when no season is passed to the action and the override select is `Auto`. |
| Scan interval | 30 s | How often to poll the App for catalog changes (10-3600 s). A change event also triggers a refresh. |
| History reset mode | `on_exhaustion` | `on_exhaustion` starts a new round when every clip has played. `daily` also resets at the reset time. |
| History reset time | `00:00:00` | Time of day for the `daily` mode. |

To change connection details, use the entry's **Reconfigure** flow. If the App rejects the saved token (for example after rotating it in **System**), Home Assistant starts a reauthentication flow where you enter the current token.

## Entities

| Entity | Description |
| --- | --- |
| `sensor.cinema_studio_active_season` | Effective season. Attributes: `source`, `collection_id`, `last_effective_season`. |
| `select.cinema_studio_season_override` | `Auto` or a season name. Takes precedence over the season entity and the calendar. |
| `sensor.cinema_studio_<collection>_last` | Last clip selected from a collection, with its metadata and the number of playable clips (`available`). |
| `sensor.cinema_studio_catalog` | Catalog revision with clip counts, unverified count and active pins. |
| `binary_sensor.cinema_studio_studio_connected` | Whether the App is currently reachable. |

Exact entity IDs depend on the names in your instance. Entities keep their cached values while the App is offline.

## Update

Update the App from the Supervisor App store and the integration through HACS; restart Home Assistant after an integration update when HACS requests it. The App's database, thumbnails and token live in its App data and are included in App backups. Originals and renders live in the Media folder, so make sure your Home Assistant backups include **Media** if you want them restored.

## Uninstall

Remove the integration through **Settings > Devices & services**; this deletes its cached catalog and history from Home Assistant storage. Uninstall the App from the App store when no longer needed. Files under `/media/cinema-studio/` are not removed automatically; delete them yourself if you no longer want them. See also [Rollback](ROLLBACK.md).
