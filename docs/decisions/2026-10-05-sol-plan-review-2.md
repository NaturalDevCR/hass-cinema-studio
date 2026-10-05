Three blockers remain:

1. **Seeded `regular` loses imported custom order.** Order is applied only to collections created during import, but `regular` already exists from seeding. Treat an untouched seed collection as eligible for initial legacy configuration/order adoption; record import ownership so reruns preserve user edits. Add a test importing custom order into seeded `regular`. ([Task 7](/Users/jdavidoa91/Dev/hass-cinema-studio/docs/superpowers/plans/2026-10-05-cinema-studio.md:937))

2. **Frozen fingerprints are not frozen render inputs.** The job freezes hashes at enqueue, but later resolves current profiles/assets. It could render new settings or replaced asset bytes while recording old fingerprints. Freeze the actual recipe, normalization targets, processing settings, original identity and immutable asset versions used by FFmpeg. Include source identity in the completion comparison so source replacement cannot clear newer pending work. ([Task 5](/Users/jdavidoa91/Dev/hass-cinema-studio/docs/superpowers/plans/2026-10-05-cinema-studio.md:878), [source repair](/Users/jdavidoa91/Dev/hass-cinema-studio/docs/superpowers/plans/2026-10-05-cinema-studio.md:967))

3. **PATCH response shapes still conflict across tracks.** Task 8 now says responses report `affected_clip_ids`, while the binding reference/client expects plain `ProcessingProfile` and `Collection` responses. Specify one exact response shape for each affected endpoint and update shared types, client methods and tests accordingly. ([Task 8](/Users/jdavidoa91/Dev/hass-cinema-studio/docs/superpowers/plans/2026-10-05-cinema-studio.md:950))

CONSENSUS: NO
