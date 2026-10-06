## 0.1.1

- Fix 4K renders with intro/outro running out of memory: each segment now uses separate video and audio inputs, the encoder thread count is configurable (`encoder_threads`, default 4) and the runtime moves to FFmpeg 8.1 (Alpine 3.24). Media processes are the preferred victims of the kernel's out-of-memory killer.
- Failed jobs show their real cause (exit code or signal, invalid output details, true-peak values) instead of the previous FFmpeg log.
- Renders that were pending when the App stopped are queued again on start; thumbnails jump ahead of queued renders and are created for imported clips.
- Library: the inline preview covers the card with native playback controls and a close button; clicking the poster opens the editor.
- Editor: pressed state for source tabs and loop, icon transport controls, trim handles that stay inside the timeline.

## 0.1.0

- Initial release of Cinema Studio as a Home Assistant Supervisor App.
- Import, trim, render and organize cinema clips into collections and seasons.
- Publish renders under `/media/cinema-studio` for the Cinema Studio integration.
