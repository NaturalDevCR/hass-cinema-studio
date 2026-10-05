**Critical:** None found.

**Important — must fix before release**

- [app/src/cinema_studio/api_v1.py:44](/Users/jdavidoa91/Dev/hass-cinema-studio/app/src/cinema_studio/api_v1.py:44): `/health` records the setup probe’s `X-Cinema-Consumer: config-flow` as a real consumer ([config_flow.py:51](/Users/jdavidoa91/Dev/hass-cinema-studio/custom_components/cinema_studio/config_flow.py:51)). No `config-flow.json` fence file is ever written, so [GC halts](/Users/jdavidoa91/Dev/hass-cinema-studio/app/src/cinema_studio/fence.py:183) for 30 days after setup, reauthentication, or reconfiguration. **Fix:** retain authentication/header validation on health, but register consumers only when serving their catalog; remove existing synthetic `config-flow` registrations. Add a setup→GC regression test. Reproduced in memory: `halted_reason='missing consumer files: config-flow'`.

**Minor — can wait**

- [app/DOCS.md:9](/Users/jdavidoa91/Dev/hass-cinema-studio/app/DOCS.md:9): Claims a folder-import screen exists. Replace with upload instructions and the `cinema_studio.import_legacy` action.
- [app/DOCS.md:19](/Users/jdavidoa91/Dev/hass-cinema-studio/app/DOCS.md:19): Claims System → Connection displays the App hostname; it displays instructions and token controls. Direct users to the Supervisor App page.
- [tests/studio/test_app_package.py:45](/Users/jdavidoa91/Dev/hass-cinema-studio/tests/studio/test_app_package.py:45): Still skips UI COPY-source validation after merge. Remove the skip; the current Dockerfile sources do exist.

**Minors-ledger triage:** None of its remaining entries warrants promotion to a release blocker.

- Resolved or superseded: status revision behavior, `clear_pending`, profile-create retry handling, upload cleanup wiring, and Organize delete-refresh handling.
- Can wait: selection-report deduplication, fallback filesystem I/O inside transactions, bulk-count semantics, stale order IDs, silent options loading, fence/history test gaps, re-verification logging flag, unload-cancellation coverage, transition clearing, untranslated job labels, DefaultsPanel draft overwrite, override failure display, and multipart OpenAPI metadata.
- The notifier-before-seed note is non-blocking: seed profile updates do not bump the catalog revision. The 70vh note remains a browser verification item.

Otherwise, the catalog fields, render naming and `media_path`, timing fields, legacy stage/commit bodies, HA entry-ID header format, consumer JSON and lock order, UI API shapes, Docker static path, media mapping, and discovery service align. Selection keys exactly match the schema; the URI contains `clip_id` and resolves under the App’s render path with the documented shared `/media` setup.

Read-only review completed with an in-memory reproduction; full tests, Docker build, and browser smoke were not run.

**RELEASE: NO.**