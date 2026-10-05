import {
  mdiCalendarBlank,
  mdiCalendarStar,
  mdiFilm,
  mdiFilmstripBox,
  mdiHalloween,
  mdiMovieOpen,
  mdiPartyPopper,
  mdiSnowflake,
} from "@mdi/js";
import { describe, expect, it } from "vitest";
import { FALLBACK_ICON, ICON_NAMES, mdiPathFor, resolveIcon } from "@/lib/icons";

describe("mdiPathFor", () => {
  it("resolves mdi:-prefixed names from the API", () => {
    expect(mdiPathFor("mdi:film")).toBe(mdiFilm);
    expect(mdiPathFor("mdi:party-popper")).toBe(mdiPartyPopper);
    expect(mdiPathFor("mdi:snowflake")).toBe(mdiSnowflake);
  });

  it("is forgiving about prefix, case and whitespace", () => {
    expect(mdiPathFor("film")).toBe(mdiFilm);
    expect(mdiPathFor("  MDI:Film ")).toBe(mdiFilm);
  });

  it("returns null for unknown or foreign icon names", () => {
    expect(mdiPathFor("mdi:definitely-not-an-icon")).toBeNull();
    expect(mdiPathFor("hass:door")).toBeNull();
    expect(mdiPathFor("")).toBeNull();
  });
});

describe("resolveIcon", () => {
  it("falls back to the generic open-movie icon", () => {
    expect(resolveIcon("mdi:nope")).toBe(mdiMovieOpen);
    expect(resolveIcon("mdi:film")).toBe(mdiFilm);
    expect(resolveIcon(null)).toBe(mdiMovieOpen);
    expect(FALLBACK_ICON).toBe(mdiMovieOpen);
  });
});

describe("backend defaults", () => {
  it("resolves every icon the Studio seeds or defaults to", () => {
    // seeded Regular collection, built-in regular season, new-season default, test factory
    const seeded = ["mdi:movie-open", "mdi:calendar-blank", "mdi:calendar-star", "mdi:filmstrip-box"];
    expect(mdiPathFor("mdi:movie-open")).toBe(mdiMovieOpen);
    expect(mdiPathFor("mdi:calendar-blank")).toBe(mdiCalendarBlank);
    expect(mdiPathFor("mdi:calendar-star")).toBe(mdiCalendarStar);
    expect(mdiPathFor("mdi:filmstrip-box")).toBe(mdiFilmstripBox);
    expect(mdiPathFor("mdi:halloween")).toBe(mdiHalloween); // example season in the docs
    for (const name of seeded) expect(ICON_NAMES).toContain(name);
  });

  it("drops the audio-only icons", () => {
    expect(mdiPathFor("mdi:music-note")).toBeNull();
    expect(mdiPathFor("mdi:speaker")).toBeNull();
  });
});

describe("curated icon set", () => {
  it("offers roughly fifty cinema-oriented icons, each resolvable", () => {
    expect(ICON_NAMES.length).toBeGreaterThanOrEqual(45);
    expect(new Set(ICON_NAMES).size).toBe(ICON_NAMES.length);
    for (const name of ICON_NAMES) {
      expect(name.startsWith("mdi:")).toBe(true);
      expect(mdiPathFor(name), name).toMatch(/^M/);
    }
  });
});
