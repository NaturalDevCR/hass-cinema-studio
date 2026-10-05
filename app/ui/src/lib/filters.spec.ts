import { describe, expect, it } from "vitest";
import { filterClips, foldText, loudnessSpread, type ClipFilter } from "@/lib/filters";
import { makeClip, makeRender, makeSeason } from "@/test/factories";

const none: ClipFilter = { collectionId: null, seasonId: null, query: "", status: null };
const ids = (clips: { id: string }[]) => clips.map((c) => c.id);

describe("foldText", () => {
  it("lowercases and strips diacritics", () => {
    expect(foldText("LEÓN Ñandú")).toBe("leon nandu");
  });
});

describe("filterClips", () => {
  const all = [
    makeClip({ id: "a", title: "León ruge", collection_id: "animals", source_name: "lion-final.mov" }),
    makeClip({ id: "b", title: "Tráiler de la puerta", collection_id: "doors", source_name: "doorbell.mp4" }),
    makeClip({ id: "c", title: "Jingle", collection_id: "christmas", status: "failed" }),
    makeClip({ id: "d", title: "Fanfare", collection_id: "regular", status: "rendering" }),
  ];
  const seasons = [
    makeSeason({ id: "xmas", collection_id: "christmas" }),
    makeSeason({ id: "regular", collection_id: "regular", builtin: true }),
  ];

  it("returns everything for an empty filter, keeping the order", () => {
    expect(ids(filterClips(all, none))).toEqual(["a", "b", "c", "d"]);
  });

  it("matches the query accent-insensitively against the title", () => {
    expect(ids(filterClips(all, { ...none, query: "leon" }))).toEqual(["a"]);
    expect(ids(filterClips(all, { ...none, query: "LEÓN" }))).toEqual(["a"]);
    expect(ids(filterClips(all, { ...none, query: "trailer" }))).toEqual(["b"]);
  });

  it("matches the source name and requires every word", () => {
    expect(ids(filterClips(all, { ...none, query: "doorbell" }))).toEqual(["b"]);
    expect(ids(filterClips(all, { ...none, query: "lion final" }))).toEqual(["a"]);
    expect(ids(filterClips(all, { ...none, query: "puerta doorbell" }))).toEqual(["b"]);
    expect(filterClips(all, { ...none, query: "puerta lion" })).toEqual([]);
  });

  it("filters by collection and by status", () => {
    expect(ids(filterClips(all, { ...none, collectionId: "doors" }))).toEqual(["b"]);
    expect(ids(filterClips(all, { ...none, status: "failed" }))).toEqual(["c"]);
  });

  it("filters by the collection a season plays", () => {
    expect(ids(filterClips(all, { ...none, seasonId: "xmas" }, seasons))).toEqual(["c"]);
    expect(ids(filterClips(all, { ...none, seasonId: "regular" }, seasons))).toEqual(["d"]);
  });

  it("matches nothing for a season that does not exist", () => {
    expect(filterClips(all, { ...none, seasonId: "gone" }, seasons)).toEqual([]);
  });

  it("combines filters with AND", () => {
    expect(filterClips(all, { ...none, collectionId: "animals", status: "failed" })).toEqual([]);
    expect(ids(filterClips(all, { ...none, seasonId: "xmas", collectionId: "christmas", query: "jin" }, seasons))).toEqual([
      "c",
    ]);
    expect(filterClips(all, { ...none, seasonId: "xmas", collectionId: "doors" }, seasons)).toEqual([]);
  });
});

describe("loudnessSpread", () => {
  const withLufs = (id: string, lufs: number | null) =>
    makeClip({ id, render: makeRender({ integrated_lufs: lufs }) });

  it("ignores clips without a measured render", () => {
    const clips = [withLufs("a", -16), withLufs("b", null), makeClip({ id: "c", render: null }), withLufs("d", -12.5)];
    const out = loudnessSpread(clips);
    expect(out).not.toBeNull();
    expect(out?.min).toBe(-16);
    expect(out?.max).toBe(-12.5);
    expect(out?.spread).toBeCloseTo(3.5);
  });

  it("returns null when nothing is measured and zero spread for a single clip", () => {
    expect(loudnessSpread([])).toBeNull();
    expect(loudnessSpread([withLufs("a", null), makeClip({ id: "b", render: null })])).toBeNull();
    expect(loudnessSpread([withLufs("a", -14)])).toEqual({ min: -14, max: -14, spread: 0 });
  });
});
