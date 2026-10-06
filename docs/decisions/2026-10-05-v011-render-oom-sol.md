**APPROVE WITH CHANGES.** The diagnosis is convincing; the base-image upgrade alone is insufficient. Splitting demuxers and limiting encoder threads address the measured memory pressure.

**A. Buffering:** The controlled comparisons strongly support audio demand driving unwanted video decoding. Splitting removes that coupling. `acrossfade` retains transition audio; `adelay` scales with configured delay; the limiter uses bounded lookahead. Your unlimited `apad` is immediately bounded by `atrim`; tail `apad` and `tpad` have explicit durations. None inherently needs whole-clip storage here. Scheduler/framesync and encoder queues remain, so this is a measured reduction, not a hard memory bound. [FFmpeg filter documentation](https://www.ffmpeg.org/ffmpeg-filters.html)

**B. Sync:** Safe provided each pair reads the same frozen file, receives identical input options, and graph labels use the correct indices. Preserve existing `trim/atrim` and timestamp resets; skip audio demuxers for silent-source substitution. Independent `PTS-STARTPTS` already removes original stream offsets—the split does not introduce that behavior. Output-measured timing remains valid, but equal stream durations cannot prove lip sync. Add coverage for nonzero trims, missing audio, fractional durations, and both joins; inspect a recognizable A/V event.

**C. Upgrade:** Acceptable, with one release gate: build the actual HA add-on image and run the full pipeline there. macOS tests plus Alpine reproduction support the choice, but do not validate HA image availability, packaged filters, or Python dependency compatibility. Check duration, transitions, LUFS and true peak; byte-identical output is unnecessary.

**D. Recovery:** Retry interrupted/pending work automatically; avoid retrying every terminal `failed` clip on every startup. Current [jobs.py:207](/Users/jdavidoa91/Dev/hass-cinema-studio/app/src/cinema_studio/jobs.py:207) does exactly that whenever `render_pending` remains true. No immediate worker loop, but persistent failures repeat across restarts. Retry these four incident failures explicitly once, or persist a bounded recovery-attempt marker. Preserve their published renders.

**E. OOM adjustment:** Reasonable best effort. Catch permission/process-exit errors and keep the parent unchanged. It biases victim selection; it neither reserves memory nor guarantees HA Core survives. A cgroup OOM is scoped to that cgroup, and group-kill configuration can kill the whole App. [Kernel OOM documentation](https://www.kernel.org/doc/html/latest/filesystems/proc.html), [cgroup documentation](https://cdn.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)

Required changes before release:

- [media.py:73](/Users/jdavidoa91/Dev/hass-cinema-studio/app/src/cinema_studio/media.py:73): Include executable and return code/signal before stderr. SIGKILL currently reports only incidental stderr; Python normally exposes it as `-9`, not Docker’s `137`. Say “SIGKILL; possible OOM,” unless independently confirmed.
- [render.py:300](/Users/jdavidoa91/Dev/hass-cinema-studio/app/src/cinema_studio/render.py:300): Preserve the failure headline during the 1,000-character truncation; otherwise `_clip_error` cannot recover it.
- Bound automatic failed-render recovery and verify interrupted work still resumes.
- Validate `encoder_threads ≥ 0`; emit output-scoped `-threads:v 4` in both mix and final passes. Verify the split-input argv and actual add-on image before release.

The inspected diff contains reporting/recovery changes, not the proposed image, demuxer, thread, or OOM changes. Approval is conditional on those implementations. Your backup and monitored rollout are reasonable; monitor the mix pass through completion before trusting the backlog.