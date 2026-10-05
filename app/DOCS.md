# Cinema Studio

Cinema Studio is a Home Assistant panel for importing, editing, rendering and organizing cinema video clips (intros, trailers and bumpers). It renders each clip to a Home Assistant compatible MP4 with normalized loudness and publishes the result for the Cinema Studio HACS integration.

## First steps

1. Open **Cinema Studio** from the Home Assistant sidebar.
2. Create collections and seasons that match how you organize your clips.
3. Upload video files on the Upload screen. To bring in clips from Cinema Collections, see the import section below.
4. Set the trim points and processing profile for each clip, then render it.
5. Install the **Cinema Studio** integration through HACS. It discovers this App automatically and loads its catalog.

## Import from Cinema Collections

If you already use the Cinema Collections integration, run its import once from **Developer Tools → Actions** with the action `cinema_studio.import_legacy`. The Cinema Studio integration reads your existing clips and sends them to the App, which copies them into its own storage. The original Cinema Collections files are not modified or deleted.

## Connecting the integration

Discovery normally configures the integration without any input. If it does not, add the **Cinema Studio** integration manually. Take the App hostname from the App's page in the Home Assistant Supervisor, use port `8099`, and copy the token from **System → Connection** in the App.

## Storage and garbage collection

The App keeps its files under `/media/cinema-studio/`:

- `originals/` holds the uploaded source files.
- `renders/` holds the published renders, named `<clip_id>-r<n>-<render_id>.mp4`.
- `assets/`, `consumers/` and `.work/` hold supporting files and scratch space.

Re-rendering a clip publishes a new render and retires the previous one. A retired (or unrecognized) render is deleted only when all of these are true:

- no consumer reports it as currently held (consumers list the renders they still need in `consumers/`);
- it is not pinned (a pin lasts 6 hours, plus a 10 minute grace period);
- it is at least 48 hours old.

Cleanup runs under an exclusive lock on `.gc.lock`. It stops without deleting anything if a consumer file is missing or unreadable, or if `/media` is on a network filesystem, because it cannot then be sure a render is unused.

## Backups

Home Assistant App backups include the Cinema Studio database, thumbnails and token in the App's data. Renders and originals live in `/media/cinema-studio`, outside App backups. Back up the `/media` share separately (for example with a media backup location or a manual copy) if you need to keep them. After restoring only the App data, re-render the clips that are missing their files.

## Troubleshooting

- If the panel does not load, check the App log and confirm the App is running.
- If the integration cannot connect, confirm it uses the App hostname shown on the App's Supervisor page, port `8099`, and the current token.
- If a clip does not play, confirm it has a finished render and that `/media` is available to Home Assistant.
- If an upload or import is missing, check the Jobs tray for an error and that the video format is supported.

## Español

Cinema Studio permite importar, editar, renderizar y organizar clips de cine para Home Assistant. Abra el panel **Cinema Studio**, cree colecciones y temporadas, y luego cargue o importe sus videos. Instale la integración Cinema Studio desde HACS; se conecta automáticamente con la aplicación. Para traer sus clips de Cinema Collections, ejecute la acción `cinema_studio.import_legacy`. Los renders se guardan en `/media/cinema-studio`, fuera de las copias de seguridad de la aplicación, por lo que debe respaldar `/media` por separado.
