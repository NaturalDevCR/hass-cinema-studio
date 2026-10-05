# Automations

`cinema_studio.select_next_clip` selects a clip and returns data for your own playback steps. It does not play video, and it does not touch projectors, screens, lights or any other device.

## Action reference

| Field | Required | Description |
| --- | --- | --- |
| `collection_id` | No | Collection ID or name. Plays from that collection regardless of season. |
| `season` | No | Season ID or name for this call only. |
| `dry_run` | No | Defaults to `false`. Verifies and returns a pick without recording history, adding a pin, firing the event or changing season activation. |

Capture the result with `response_variable`. The action fires the event `cinema_studio_selected` (same data as the response) for each recorded selection.

### Errors

Errors are validation errors. Use `continue_on_error: true` if your script has a fallback.

| Key | Meaning |
| --- | --- |
| `not_ready` | The catalog, history or verification has not loaded yet, or the lock shared with the App could not be taken or written. No unpinned clip is ever returned. |
| `no_playable_clip` | The season's collection and the Regular fallback have no verified, enabled clip. |
| `unknown_collection` | `collection_id` does not match a collection. |
| `unknown_season` | `season` does not match a season. |

## Response contract (version 1)

The response is flat. Every field is always present. The machine-readable definition is [`contract/selection_response.schema.json`](../contract/selection_response.schema.json); durations and offsets are in seconds, rounded to 3 decimals.

| Field | Type | Description |
| --- | --- | --- |
| `contract_version` | `1` | Always `1`. Consumers must reject any other value. |
| `instance_id` | string | Identity of the Cinema Studio App instance. |
| `catalog_revision` | integer | Catalog revision the pick came from. |
| `selection_id` | string | Unique ID of this selection. |
| `selected_at` | string (date-time) | UTC timestamp of the selection. |
| `collection_id` | string | Collection the clip was picked from. |
| `season` | string | Season actually used (`regular` after a fallback). |
| `requested_season` | string | Season that was resolved before any fallback. |
| `season_source` | `action` \| `override` \| `entity` \| `calendar` \| `default` | How the season was resolved. |
| `season_fallback` | boolean | `true` when the season's collection had nothing playable and the Regular collection was used. |
| `playback_mode` | `random` \| `sequential` \| `custom` | Mode of the collection. |
| `history_reset` | boolean | A new playback round started with this pick. |
| `activation_reset` | boolean | A season change reset the collection's history on this call. |
| `clip_id` | string | Clip identifier (stable, an imported clip keeps its original ID). |
| `title` | string | Clip title. |
| `source_name` | string | Original source name. |
| `render_id` | string | ID of the immutable render. |
| `render_n` | integer >= 1 | Render counter for the clip. |
| `relative_output_path` | string | Path relative to the Media folder: `cinema-studio/renders/<clip_id>/<file>.mp4`. |
| `media_content_id` | string | `media-source://media_source/local/cinema-studio/renders/...` URI. Contains the `clip_id`. |
| `media_content_type` | `video` | Always `video`. |
| `duration_seconds` | number (0, 7200] | Total file duration. |
| `duration` | number (0, 7200] | Same value as `duration_seconds`. |
| `content_duration` | number | Length of the content region (`content_end_offset - content_start_offset`). |
| `lead_in_duration` | number | Black/silent margin before the content. Equals `content_start_offset`. |
| `tail_out_duration` | number | Black/silent margin after the content (`duration - content_end_offset`). |
| `content_start_offset` | number | Where the content starts in the file. |
| `content_end_offset` | number | Where the content ends in the file. |
| `timing_source` | `measured` \| `legacy_worker` \| `legacy_full_file` | Where the timing came from: measured by Cinema Studio, taken from an imported Cinema Collections output, or an imported file with no timing data (content spans the whole file). |
| `timing_verified` | `true` | Timing passed the validation rules. Never `false` in a response. |
| `file_verified` | `true` | The render file exists inside `cinema-studio/renders/`, is a regular file and has the cataloged size, checked in this call. Never `false` in a response. |
| `render_pending` | boolean | The clip was edited and a new render is queued; this response still describes the current published render. |
| `output_is_stale` | boolean | Same as `render_pending` (compatibility with Cinema Collections). |
| `size` | integer >= 1 | File size in bytes. |
| `sha256` | string | Render hash (diagnostic; not recomputed by Home Assistant). |
| `profile_fingerprint` | string | Hash of the normalization, cast profile and recipe used. |

Timing is guaranteed to satisfy: `0 < duration <= 7200`; `content_start_offset == lead_in_duration`; `0 <= content_start_offset < content_end_offset <= duration`; `content_duration` equals `content_end_offset - content_start_offset` and `tail_out_duration` equals `duration - content_end_offset`, each within 0.001 s. A margin of `0` is a valid value (for example `lead_in_duration: 0` means the content starts immediately). Clips with unknown or invalid timing are never returned.

## Basic example

```yaml
alias: Play the next cinema clip
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

Preview a pick without changing history: `data: {dry_run: true}`. Force a collection or season for one call: `data: {collection_id: halloween}` or `data: {season: christmas}`.

## Validating the response in a projector script

If the selected clip drives expensive or shared hardware (projector, screen, lighting, audio zones), validate the response before using it. Check at least:

1. `contract_version == 1`. Anything else means the contract changed and the script must not trust it.
2. `timing_verified` is `true` and `file_verified` is `true`.
3. `clip_id` and `media_content_id` are non-empty and `media_content_id` contains `clip_id`. Scripts that confirm playback by looking for the clip ID in the player's `media_content_id` depend on this; Cinema Studio file names always include it.
4. The timing numbers are numeric and consistent: `duration > 0`, `0 <= content_start_offset < content_end_offset <= duration`, `abs(content_duration - (content_end_offset - content_start_offset)) <= 0.001`, `abs(tail_out_duration - (duration - content_end_offset)) <= 0.001`.

Anything else (an error, a missing response, a failed check) should take your fallback path.

## Fallback pattern

This example wraps the new path and the fallback in one script that returns a single `result` object, so the rest of your playback script maps from `result` regardless of which path produced it. It calls Cinema Studio first, validates the response, and falls back to the previous product (`cinema_collections` plus a metadata step) when the action errors or the response is not valid. The fallback entity and service names are illustrative; keep your existing steps there.

Returning the values with `stop` and `response_variable` avoids depending on how Home Assistant scopes variables set inside `choose` branches. If you prefer to keep everything in one script, define the mapped variables at the top level of that script.

```yaml
script:
  select_clip_with_fallback:
    mode: single
    sequence:
      - variables:
          selection: {}      # replaced by the response; stays {} if the action fails

      # --- New path ---------------------------------------------------
      - action: cinema_studio.select_next_clip
        continue_on_error: true
        response_variable: selection

      - variables:
          selection_ok: >-
            {% set s = selection if selection is mapping else {} %}
            {{
              s.get('contract_version') == 1
              and s.get('timing_verified') == true
              and s.get('file_verified') == true
              and (s.get('clip_id') | default('', true) | string) != ''
              and (s.get('media_content_id') | default('', true) | string) != ''
              and s.get('clip_id') in s.get('media_content_id')
              and s.get('duration') is number
              and s.get('content_start_offset') is number
              and s.get('content_end_offset') is number
              and s.get('content_duration') is number
              and s.get('lead_in_duration') is number
              and s.get('tail_out_duration') is number
              and s.get('duration') > 0
              and s.get('content_start_offset') >= 0
              and s.get('content_start_offset') < s.get('content_end_offset')
              and s.get('content_end_offset') <= s.get('duration')
              and (s.get('content_duration') - (s.get('content_end_offset') - s.get('content_start_offset'))) | abs <= 0.001
              and (s.get('tail_out_duration') - (s.get('duration') - s.get('content_end_offset'))) | abs <= 0.001
            }}

      - choose:
          - conditions: "{{ selection_ok }}"
            sequence:
              - variables:
                  result:
                    used_fallback: false
                    clip_id: "{{ selection.clip_id }}"
                    clip_uri: "{{ selection.media_content_id }}"
                    clip_name: "{{ selection.title }}"
                    duration: "{{ selection.duration }}"
                    content_start: "{{ selection.content_start_offset }}"
                    content_end: "{{ selection.content_end_offset }}"
                    lead_in: "{{ selection.lead_in_duration }}"
                    tail_out: "{{ selection.tail_out_duration }}"
              - stop: Selected with Cinema Studio
                response_variable: result

      # --- Fallback: your previous steps, unchanged (illustrative) -----
      - event: cinema_selection_fallback      # optional: count fallbacks
      - action: cinema_collections.select_next_clip
        response_variable: old_selection
      - action: shell_command.cinema_clip_metadata
        data:
          clip_id: "{{ old_selection.clip_id }}"
        response_variable: old_metadata
      - variables:
          result:
            used_fallback: true
            clip_id: "{{ old_selection.clip_id }}"
            clip_uri: "{{ old_selection.media_content_id }}"
            # Map clip_name, duration, content_start, content_end, lead_in and
            # tail_out from your existing metadata step here.
      - stop: Selected with the fallback
        response_variable: result
```

Call it from your playback script, before the first device action:

```yaml
- action: script.select_clip_with_fallback
  response_variable: sel
# use {{ sel.clip_uri }}, {{ sel.duration }}, {{ sel.content_start }} ...
```

Notes:

- `continue_on_error: true` keeps the script running when the action raises. `selection` then keeps its initial `{}`, which fails validation and takes the fallback.
- The fallback runs only inside this block, before any device step. Nothing after the first device action should change.
- Keep the old product enabled while you use a fallback: it records its own history. The two histories are independent, so a session that falls back can repeat a clip that Cinema Studio already played; this only matters on fallbacks.
- Count fallbacks (the event above, a counter helper or your own log) and confirm the count stays at zero before removing the fallback block. See [Migration](migration.md).
- To test without side effects, run a copy of the block with `dry_run: true` on both services; see the self-test in the migration guide.

## Season examples

Leave the season to Cinema Studio (calendar, override select or season entity). To pin a season for one call, pass it:

```yaml
- action: cinema_studio.select_next_clip
  data:
    season: halloween
  response_variable: clip
```

To follow an existing helper that holds your season, set it as the **Season entity** in the integration options; its state may be a season ID or a name (`unknown`, `unavailable` and empty are ignored). The `select.cinema_studio_season_override` entity beats the season entity.
