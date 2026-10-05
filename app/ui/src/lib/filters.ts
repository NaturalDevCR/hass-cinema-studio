import type { Clip, ClipStatus, Season } from "@/api/types";

export type ClipFilter = {
  collectionId: string | null;
  seasonId: string | null;
  query: string;
  status: ClipStatus | null;
};

/** Lowercases and strips diacritics so "León" and "leon" compare equal. */
export function foldText(text: string): string {
  return text.normalize("NFD").replace(/\p{M}+/gu, "").toLowerCase();
}

/**
 * Applies every active filter (AND). The query is split into words that must all appear in
 * the title or the source file name. A season filter keeps the clips of the collection that
 * season plays, so `seasons` has to be passed along with it; an unknown season matches nothing.
 */
export function filterClips(clips: Clip[], f: ClipFilter, seasons: Season[] = []): Clip[] {
  const words = foldText(f.query).split(/\s+/).filter(Boolean);
  const seasonCollection = f.seasonId === null ? null : (seasons.find((s) => s.id === f.seasonId)?.collection_id ?? "");
  return clips.filter((c) => {
    if (f.collectionId !== null && c.collection_id !== f.collectionId) return false;
    if (seasonCollection !== null && c.collection_id !== seasonCollection) return false;
    if (f.status !== null && c.status !== f.status) return false;
    if (words.length) {
      const haystack = foldText(`${c.title} ${c.source_name}`);
      if (!words.every((w) => haystack.includes(w))) return false;
    }
    return true;
  });
}

/** Min/max integrated loudness across rendered clips; null when none is measured. */
export function loudnessSpread(clips: Clip[]): { min: number; max: number; spread: number } | null {
  const values = clips
    .map((c) => c.render?.integrated_lufs)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (!values.length) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  return { min, max, spread: max - min };
}
