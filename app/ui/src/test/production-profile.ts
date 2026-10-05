// Verbatim copy of the production processing profile (settings as stored by Clips). It has no
// `profile_version`: the form must round-trip it exactly, without adding or dropping keys.
import type { ProcessingProfile } from "@/api/types";

export const productionProfile = {
  id: "4k-loudness-with-intro",
  name: "4K con intro y audio normalizado",
  settings: {
    audio: {
      bitrate_kbps: 192,
      channels: 2,
      codec: "aac",
      fallback: "none",
      missing_policy: {
        mode: "required"
      },
      pad_or_trim: true,
      sample_rate: 48000
    },
    decode_error_policy: "warn",
    fade_in_seconds: 1,
    fade_out_seconds: 1.5,
    hardware_acceleration: false,
    intro_reference: "treebu-hotels-intro.mp4",
    loudness: {
      final_mix_normalization: true,
      integrated_lufs: -18,
      lra_lu: 11,
      mode: "two_pass",
      true_peak_dbtp: -1.5
    },
    minimum_segment_duration_seconds: null,
    output: {
      atomic_finalize: true,
      container: "mp4",
      extension: "mp4",
      temporary_output: true
    },
    outro_reference: "treebu-hotels-intro.mp4",
    timeout_seconds: 300,
    timeout_seconds_per_minute: 120,
    transitions: [
      {
        duration_seconds: 1,
        from_segment: "intro",
        to_segment: "clip",
        type: "fade"
      },
      {
        duration_seconds: 1,
        from_segment: "clip",
        to_segment: "outro",
        type: "fade"
      }
    ],
    video: {
      bufsize_kbps: 40000,
      codec: "libx264",
      fast_start: true,
      fps: 24,
      "h264_profile": "high",
      height: 2160,
      keyframe_interval_seconds: 2,
      level: "5.1",
      maxrate_kbps: 20000,
      pixel_format: "yuv420p",
      preset: "fast",
      quality: {
        crf: 23,
        mode: "crf"
      },
      scaling: {
        height: 2160,
        sar_den: 1,
        sar_num: 1,
        strategy: "aspect_fit",
        width: 3840
      },
      width: 3840
    }
  },
} as unknown as ProcessingProfile;
