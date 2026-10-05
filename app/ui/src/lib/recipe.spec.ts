import { describe, expect, it } from "vitest";
import { defaultRecipe, recipesEqual, trimmedLength, validateRecipe } from "@/lib/recipe";
import type { OriginalInfo, Recipe, Settings } from "@/api/types";

const settings: Settings = {
  max_upload_mb: 2048,
  max_duration_s: 7200,
  default_lead_in: 1.5,
  default_tail_out: 2.5,
  disk_reserve_bytes: 5_000_000_000,
  test_targets: [],
  protected_entities: [],
};

const original: OriginalInfo = {
  filename: "trailer.mp4",
  size: 1000,
  sha256: "abc",
  duration: 10,
  width: 1920,
  height: 1080,
  fps: 24,
  has_audio: true,
  video_codec: "h264",
};

const base = (patch: Partial<Recipe> = {}): Recipe => ({ ...defaultRecipe(settings), ...patch });
const problems = (patch: Partial<Recipe>, info: OriginalInfo = original) => validateRecipe(base(patch), info);

describe("defaultRecipe", () => {
  it("leaves the clip untouched and takes the margins from the settings", () => {
    expect(defaultRecipe(settings)).toEqual({
      trim_start: 0,
      trim_end: null,
      crop: null,
      fade_in: null,
      fade_out: null,
      gain_db: 0,
      profile_id: null,
      lead_in: 1.5,
      tail_out: 2.5,
    });
  });

  it("returns a fresh object each time", () => {
    expect(defaultRecipe(settings)).not.toBe(defaultRecipe(settings));
  });
});

describe("trimmedLength", () => {
  it("uses the full duration when trim_end is null", () => {
    expect(trimmedLength(base(), 10)).toBe(10);
    expect(trimmedLength(base({ trim_start: 2 }), 10)).toBe(8);
  });

  it("uses trim_end when set and never exceeds the file", () => {
    expect(trimmedLength(base({ trim_start: 2, trim_end: 5 }), 10)).toBe(3);
    expect(trimmedLength(base({ trim_end: 99 }), 10)).toBe(10);
  });

  it("never goes negative", () => {
    expect(trimmedLength(base({ trim_start: 7, trim_end: 4 }), 10)).toBe(0);
    expect(trimmedLength(base({ trim_start: 20 }), 10)).toBe(0);
  });
});

describe("validateRecipe (mirrors Recipe.validate_for)", () => {
  it("accepts the default recipe and a sensible edit", () => {
    expect(problems({})).toEqual([]);
    expect(
      problems({
        trim_start: 1,
        trim_end: 6,
        crop: { x: 100, y: 50, w: 1280, h: 720 },
        fade_in: 0.5,
        fade_out: 1,
        gain_db: 3,
        profile_id: "loud",
        lead_in: 0,
        tail_out: 10,
      }),
    ).toEqual([]);
  });

  const table: [string, Partial<Recipe>, string][] = [
    ["start not before end", { trim_start: 5, trim_end: 5 }, "recipe.error.trimOrder"],
    ["start after end", { trim_start: 6, trim_end: 2 }, "recipe.error.trimOrder"],
    ["start at the end of the file", { trim_start: 10 }, "recipe.error.trimOrder"],
    ["negative start", { trim_start: -1 }, "recipe.error.trimStart"],
    ["end past the file", { trim_end: 12 }, "recipe.error.trimEnd"],
    ["crop wider than the source", { crop: { x: 0, y: 0, w: 2000, h: 720 } }, "recipe.error.cropBounds"],
    ["crop below the source", { crop: { x: 0, y: 1000, w: 640, h: 200 } }, "recipe.error.cropBounds"],
    ["crop with a negative origin", { crop: { x: -2, y: 0, w: 640, h: 360 } }, "recipe.error.cropBounds"],
    ["crop narrower than 64 px", { crop: { x: 0, y: 0, w: 62, h: 360 } }, "recipe.error.cropMin"],
    ["crop shorter than 64 px", { crop: { x: 0, y: 0, w: 640, h: 63 } }, "recipe.error.cropMin"],
    ["negative fade in", { fade_in: -1 }, "recipe.error.fadeNegative"],
    ["negative fade out", { fade_out: -0.1 }, "recipe.error.fadeNegative"],
    ["fades longer than the trim", { trim_end: 2, fade_in: 1.5, fade_out: 1 }, "recipe.error.fadeLong"],
    ["gain too high", { gain_db: 25 }, "recipe.error.gainRange"],
    ["gain too low", { gain_db: -24.5 }, "recipe.error.gainRange"],
    ["negative lead-in", { lead_in: -0.5 }, "recipe.error.marginRange"],
    ["lead-in over 10 s", { lead_in: 10.5 }, "recipe.error.marginRange"],
    ["negative tail-out", { tail_out: -1 }, "recipe.error.marginRange"],
    ["tail-out over 10 s", { tail_out: 11 }, "recipe.error.marginRange"],
    ["a NaN", { gain_db: Number.NaN }, "recipe.error.number"],
    ["an infinite fade", { fade_in: Number.POSITIVE_INFINITY }, "recipe.error.number"],
    ["a NaN crop value", { crop: { x: Number.NaN, y: 0, w: 640, h: 360 } }, "recipe.error.number"],
  ];
  it.each(table)("rejects %s", (_name, patch, key) => {
    expect(problems(patch)).toContain(key);
  });

  it("accepts values on the boundaries", () => {
    expect(problems({ gain_db: 24 })).toEqual([]);
    expect(problems({ gain_db: -24 })).toEqual([]);
    expect(problems({ lead_in: 0, tail_out: 10 })).toEqual([]);
    expect(problems({ crop: { x: 0, y: 0, w: 64, h: 64 } })).toEqual([]);
    expect(problems({ crop: { x: 0, y: 0, w: 1920, h: 1080 } })).toEqual([]);
    expect(problems({ trim_end: 4, fade_in: 2, fade_out: 2 })).toEqual([]);
  });

  it("allows the trim to overshoot the file by the 0.05 s the server tolerates", () => {
    expect(problems({ trim_end: 10.05 })).toEqual([]);
    expect(problems({ trim_end: 10.06 })).toContain("recipe.error.trimEnd");
  });

  it("treats null fades as profile fades and never measures them against the trim", () => {
    expect(problems({ trim_end: 1, fade_in: null, fade_out: 0.9 })).toEqual([]);
    expect(problems({ trim_end: 1, fade_in: null, fade_out: 1.2 })).toContain("recipe.error.fadeLong");
  });

  it("reports every problem at once, and only once each", () => {
    const out = problems({ trim_start: -1, trim_end: 12, gain_db: 30, lead_in: 20, tail_out: 20 });
    expect(out).toEqual([
      "recipe.error.trimStart",
      "recipe.error.trimEnd",
      "recipe.error.gainRange",
      "recipe.error.marginRange",
    ]);
  });

  it("measures the crop against the source of this clip", () => {
    expect(problems({ crop: { x: 0, y: 0, w: 1280, h: 720 } }, { ...original, width: 1280, height: 720 })).toEqual([]);
    expect(problems({ crop: { x: 0, y: 0, w: 1280, h: 720 } }, { ...original, width: 1000, height: 720 })).toContain(
      "recipe.error.cropBounds",
    );
  });
});

describe("recipesEqual", () => {
  it("compares every field", () => {
    expect(recipesEqual(base(), base())).toBe(true);
    expect(recipesEqual(base({ trim_end: null }), base({ trim_end: 4 }))).toBe(false);
    expect(recipesEqual(base({ profile_id: "a" }), base({ profile_id: "b" }))).toBe(false);
    expect(recipesEqual(base({ lead_in: 1 }), base({ lead_in: 2 }))).toBe(false);
    expect(recipesEqual(base({ tail_out: 1 }), base({ tail_out: 2 }))).toBe(false);
  });

  it("distinguishes a null fade (profile) from an explicit zero", () => {
    expect(recipesEqual(base({ fade_in: null }), base({ fade_in: 0 }))).toBe(false);
    expect(recipesEqual(base({ fade_out: null }), base({ fade_out: null }))).toBe(true);
    expect(recipesEqual(base({ fade_out: 1 }), base({ fade_out: 1.5 }))).toBe(false);
  });

  it("compares crops by value", () => {
    const crop = { x: 0, y: 0, w: 640, h: 360 };
    expect(recipesEqual(base({ crop }), base({ crop: { ...crop } }))).toBe(true);
    expect(recipesEqual(base({ crop }), base({ crop: null }))).toBe(false);
    expect(recipesEqual(base({ crop }), base({ crop: { ...crop, w: 642 } }))).toBe(false);
    expect(recipesEqual(base({ crop: null }), base({ crop: null }))).toBe(true);
  });

  it("ignores floating point noise", () => {
    expect(recipesEqual(base({ gain_db: 0.1 + 0.2 }), base({ gain_db: 0.3 }))).toBe(true);
    expect(recipesEqual(base({ gain_db: 0.5 }), base({ gain_db: 0.6 }))).toBe(false);
  });
});
