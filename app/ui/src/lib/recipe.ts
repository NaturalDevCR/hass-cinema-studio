import type { OriginalInfo, Recipe, Settings } from "@/api/types";
import type { MessageKey } from "@/i18n";

export const GAIN_MIN = -24;
export const GAIN_MAX = 24;
export const MARGIN_MAX = 10;
export const CROP_MIN = 64;
/** Seconds a trim may overshoot the file (the server's tolerance). */
const TRIM_TOLERANCE = 0.05;
/** Slack for fades measured against the trimmed length (float noise only). */
const EPSILON = 1e-6;

const near = (a: number, b: number) => Math.abs(a - b) <= EPSILON;
const nearOrNull = (a: number | null, b: number | null) =>
  a === null || b === null ? a === b : near(a, b);

/** A new recipe: whole clip, no crop, profile fades, no gain, margins from the settings. */
export function defaultRecipe(settings: Pick<Settings, "default_lead_in" | "default_tail_out">): Recipe {
  return {
    trim_start: 0,
    trim_end: null,
    crop: null,
    fade_in: null,
    fade_out: null,
    gain_db: 0,
    profile_id: null,
    lead_in: settings.default_lead_in,
    tail_out: settings.default_tail_out,
  };
}

export function recipesEqual(a: Recipe, b: Recipe): boolean {
  const sameCrop =
    a.crop === null || b.crop === null
      ? a.crop === b.crop
      : near(a.crop.x, b.crop.x) && near(a.crop.y, b.crop.y) && near(a.crop.w, b.crop.w) && near(a.crop.h, b.crop.h);
  return (
    sameCrop &&
    near(a.trim_start, b.trim_start) &&
    nearOrNull(a.trim_end, b.trim_end) &&
    nearOrNull(a.fade_in, b.fade_in) &&
    nearOrNull(a.fade_out, b.fade_out) &&
    near(a.gain_db, b.gain_db) &&
    a.profile_id === b.profile_id &&
    near(a.lead_in, b.lead_in) &&
    near(a.tail_out, b.tail_out)
  );
}

/** Seconds of the original that survive the trim. Never negative, never longer than the file. */
export function trimmedLength(r: Recipe, duration: number): number {
  const end = Math.min(r.trim_end ?? duration, duration);
  return Math.max(0, end - Math.max(0, r.trim_start));
}

/**
 * i18n keys (`recipe.error.*`) for everything the server would reject (`Recipe.validate_for`);
 * empty when the recipe is valid. The profile id is checked server-side.
 */
export function validateRecipe(r: Recipe, original: OriginalInfo): MessageKey[] {
  const { duration } = original;
  const numbers = [r.trim_start, r.trim_end ?? 0, r.fade_in ?? 0, r.fade_out ?? 0, r.gain_db, r.lead_in, r.tail_out];
  if (r.crop) numbers.push(r.crop.x, r.crop.y, r.crop.w, r.crop.h);
  if (!numbers.every(Number.isFinite)) return ["recipe.error.number"];

  const problems: MessageKey[] = [];
  const end = r.trim_end ?? duration;
  if (r.trim_start < -TRIM_TOLERANCE) problems.push("recipe.error.trimStart");
  if (r.trim_end !== null && r.trim_end > duration + TRIM_TOLERANCE) problems.push("recipe.error.trimEnd");
  const ordered = r.trim_start < end;
  if (!ordered) problems.push("recipe.error.trimOrder");

  if (r.crop) {
    const { x, y, w, h } = r.crop;
    if (x < 0 || y < 0 || x + w > original.width || y + h > original.height) problems.push("recipe.error.cropBounds");
    if (w < CROP_MIN || h < CROP_MIN) problems.push("recipe.error.cropMin");
  }

  if ((r.fade_in ?? 0) < 0 || (r.fade_out ?? 0) < 0) {
    problems.push("recipe.error.fadeNegative");
  } else if (ordered && (r.fade_in ?? 0) + (r.fade_out ?? 0) > trimmedLength(r, duration) + EPSILON) {
    problems.push("recipe.error.fadeLong");
  }

  if (r.gain_db < GAIN_MIN || r.gain_db > GAIN_MAX) problems.push("recipe.error.gainRange");
  if (r.lead_in < 0 || r.lead_in > MARGIN_MAX || r.tail_out < 0 || r.tail_out > MARGIN_MAX) {
    problems.push("recipe.error.marginRange");
  }
  return problems;
}
