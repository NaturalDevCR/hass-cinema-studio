import type { Clip, ClipStatus } from "@/api/types";

export type ClipFilter = {
  collectionId: string | null;
  /** The selected season (UI identity only; it does not filter by itself). */
  seasonId: string | null;
  /**
   * The collection the selected season plays, resolved by the caller (e.g. from
   * `useStudio().seasonById(seasonId)?.collection_id`). When non-null the clips are restricted
   * to that collection; null means no season constraint.
   */
  seasonCollectionId: string | null;
  query: string;
  status: ClipStatus | null;
};

/** Lowercases and strips diacritics so "León" and "leon" compare equal. */
export function foldText(text: string): string {
  return text.normalize("NFD").replace(/\p{M}+/gu, "").toLowerCase();
}

/**
 * Applies every active filter (AND). The query is split into words that must all appear in
 * the title or the source file name. The season filter is the explicit `seasonCollectionId`
 * the caller resolved, so nothing is looked up (or silently dropped) in here.
 */
export function filterClips(clips: Clip[], f: ClipFilter): Clip[] {
  const words = foldText(f.query).split(/\s+/).filter(Boolean);
  return clips.filter((c) => {
    if (f.collectionId !== null && c.collection_id !== f.collectionId) return false;
    if (f.seasonCollectionId !== null && c.collection_id !== f.seasonCollectionId) return false;
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
