import { describe, expect, it } from "vitest";
import {
  formatBytes,
  formatDateTime,
  formatDb,
  formatDuration,
  formatLufs,
  formatTimecode,
} from "@/lib/format";

describe("formatDuration", () => {
  it("formats seconds with one decimal", () => {
    expect(formatDuration(2.5)).toBe("0:02.5");
    expect(formatDuration(75.04)).toBe("1:15.0");
    expect(formatDuration(0)).toBe("0:00.0");
  });

  it("shows a clip length as minutes:seconds.tenths", () => {
    expect(formatDuration(154.133)).toBe("2:34.1");
  });

  it("carries rounding into the next minute", () => {
    expect(formatDuration(59.96)).toBe("1:00.0");
  });

  it("keeps counting minutes past one hour and clamps bad input", () => {
    expect(formatDuration(3725.2)).toBe("62:05.2");
    expect(formatDuration(-4)).toBe("0:00.0");
    expect(formatDuration(Number.NaN)).toBe("0:00.0");
  });
});

describe("formatTimecode", () => {
  it("formats HH:MM:SS.mmm", () => {
    expect(formatTimecode(154.133)).toBe("00:02:34.133");
    expect(formatTimecode(0)).toBe("00:00:00.000");
    expect(formatTimecode(3725.2)).toBe("01:02:05.200");
  });

  it("carries millisecond rounding and clamps bad input", () => {
    expect(formatTimecode(59.9996)).toBe("00:01:00.000");
    expect(formatTimecode(-4)).toBe("00:00:00.000");
    expect(formatTimecode(Number.NaN)).toBe("00:00:00.000");
  });
});

describe("formatLufs", () => {
  it("uses a true minus sign and one decimal", () => {
    expect(formatLufs(-16.04)).toBe("−16.0 LUFS");
    expect(formatLufs(-13)).toBe("−13.0 LUFS");
  });

  it("renders a dash for missing loudness", () => {
    expect(formatLufs(null)).toBe("—");
  });

  it("never prints a negative zero", () => {
    expect(formatLufs(-0.02)).toBe("0.0 LUFS");
  });
});

describe("formatDb", () => {
  it("signs positive and negative gains", () => {
    expect(formatDb(2)).toBe("+2.0 dB");
    expect(formatDb(-3)).toBe("−3.0 dB");
    expect(formatDb(-0.5)).toBe("−0.5 dB");
  });

  it("collapses zero (and values that round to zero) to plain 0 dB", () => {
    expect(formatDb(0)).toBe("0 dB");
    expect(formatDb(-0.04)).toBe("0 dB");
  });
});

describe("formatBytes", () => {
  it("scales through binary units", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(1048576)).toBe("1.0 MB");
    expect(formatBytes(5 * 1024 ** 3)).toBe("5.0 GB");
  });
});

describe("formatDateTime", () => {
  it("returns a dash for null or invalid input", () => {
    expect(formatDateTime(null, "en")).toBe("—");
    expect(formatDateTime("not a date", "es")).toBe("—");
  });

  it("formats in the requested locale", () => {
    const iso = "2026-10-31T18:30:00Z";
    const en = formatDateTime(iso, "en");
    const es = formatDateTime(iso, "es");
    expect(en).toContain("2026");
    expect(es).toContain("2026");
    expect(en).not.toBe(es);
  });
});
