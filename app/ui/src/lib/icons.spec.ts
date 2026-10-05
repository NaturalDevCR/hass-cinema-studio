import {
  mdiCalendarBlank,
  mdiCalendarStar,
  mdiDoorOpen,
  mdiHalloween,
  mdiMusicNote,
  mdiPartyPopper,
  mdiSnowflake,
} from "@mdi/js";
import { describe, expect, it } from "vitest";
import { ICON_NAMES, mdiPathFor, resolveIcon } from "@/lib/icons";

describe("mdiPathFor", () => {
  it("resolves mdi:-prefixed names from the API", () => {
    expect(mdiPathFor("mdi:door-open")).toBe(mdiDoorOpen);
    expect(mdiPathFor("mdi:party-popper")).toBe(mdiPartyPopper);
    expect(mdiPathFor("mdi:snowflake")).toBe(mdiSnowflake);
  });

  it("is forgiving about prefix, case and whitespace", () => {
    expect(mdiPathFor("door-open")).toBe(mdiDoorOpen);
    expect(mdiPathFor("  MDI:Door-Open ")).toBe(mdiDoorOpen);
  });

  it("returns null for unknown or foreign icon names", () => {
    expect(mdiPathFor("mdi:definitely-not-an-icon")).toBeNull();
    expect(mdiPathFor("hass:door")).toBeNull();
    expect(mdiPathFor("")).toBeNull();
  });
});

describe("resolveIcon", () => {
  it("falls back to the generic music note", () => {
    expect(resolveIcon("mdi:nope")).toBe(mdiMusicNote);
    expect(resolveIcon("mdi:door-open")).toBe(mdiDoorOpen);
    expect(resolveIcon(null)).toBe(mdiMusicNote);
  });
});

describe("backend defaults", () => {
  it("resolves every icon the Studio seeds or defaults to", () => {
    // regular season, new-season default, seeded "general" category
    expect(mdiPathFor("mdi:calendar-blank")).toBe(mdiCalendarBlank);
    expect(mdiPathFor("mdi:calendar-star")).toBe(mdiCalendarStar);
    expect(mdiPathFor("mdi:music-note")).toBe(mdiMusicNote);
    expect(mdiPathFor("mdi:halloween")).toBe(mdiHalloween); // example season in the docs
    for (const name of ["mdi:calendar-blank", "mdi:calendar-star", "mdi:music-note"]) {
      expect(ICON_NAMES).toContain(name);
    }
  });
});

describe("curated icon set", () => {
  it("offers roughly sixty icons, each resolvable", () => {
    expect(ICON_NAMES.length).toBeGreaterThanOrEqual(55);
    expect(new Set(ICON_NAMES).size).toBe(ICON_NAMES.length);
    for (const name of ICON_NAMES) {
      expect(name.startsWith("mdi:")).toBe(true);
      expect(mdiPathFor(name), name).toMatch(/^M/);
    }
  });
});
