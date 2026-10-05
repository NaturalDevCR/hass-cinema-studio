import { beforeEach, describe, expect, it, vi } from "vitest";
import { en } from "@/i18n/en";
import { es } from "@/i18n/es";
import { detectLocale, translate, translatePlural, useI18n } from "@/i18n";

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("message catalogs", () => {
  it("has a Spanish entry for every English key and no extras", () => {
    const enKeys = Object.keys(en).sort();
    const esKeys = Object.keys(es).sort();
    expect(esKeys.filter((k) => !enKeys.includes(k))).toEqual([]);
    expect(enKeys.filter((k) => !esKeys.includes(k))).toEqual([]);
  });

  it("has no empty strings", () => {
    for (const [key, value] of [...Object.entries(en), ...Object.entries(es)]) {
      expect(value.trim(), key).not.toBe("");
    }
  });

  it("uses the same {placeholders} in both languages", () => {
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(placeholders(es[key]), key).toEqual(placeholders(en[key]));
    }
  });

  it("defines .one and .other together", () => {
    const keys = Object.keys(en);
    for (const key of keys.filter((k) => k.endsWith(".one"))) {
      expect(keys, key).toContain(key.replace(/\.one$/, ".other"));
    }
    for (const key of keys.filter((k) => k.endsWith(".other"))) {
      expect(keys, key).toContain(key.replace(/\.other$/, ".one"));
    }
  });

  it("uses flat dotted keys", () => {
    for (const key of Object.keys(en)) expect(key).toMatch(/^[a-z][A-Za-z0-9]*(\.[A-Za-z0-9_]+)+$/);
  });
});

describe("useI18n", () => {
  beforeEach(() => {
    localStorage.clear();
    useI18n().setLocale("en");
  });

  it("interpolates {n}-style params and leaves unknown ones visible", () => {
    const { t } = useI18n();
    expect(t("jobs.active", { n: 3 })).toContain("3");
    expect(t("jobs.active", { n: 3 })).not.toContain("{n}");
    expect(translate("jobs.active")).toContain("{n}");
  });

  it("picks the singular for exactly one and the plural otherwise", () => {
    expect(translatePlural("profile.queued", 1)).toBe("1 clip queued for rendering");
    expect(translatePlural("profile.queued", 0)).toBe("0 clips queued for rendering");
    expect(translatePlural("profile.queued", 12)).toBe("12 clips queued for rendering");
    expect(useI18n().tp("profile.rerender", 3)).toBe("Re-render 3 clips now?");
    useI18n().setLocale("es");
    expect(translatePlural("profile.queued", 1)).toBe("1 clip en cola para renderizar");
    expect(translatePlural("profile.queued", 2)).toBe("2 clips en cola para renderizar");
  });

  it("names the app and sections for video", () => {
    expect(en["app.name"]).toBe("Cinema Studio");
    expect(es["app.name"]).toBe("Cinema Studio");
    expect(en["nav.library"]).toBe("Library");
  });

  it("switches language reactively and persists the choice", () => {
    const { t, locale, setLocale } = useI18n();
    expect(t("nav.library")).toBe(en["nav.library"]);
    setLocale("es");
    expect(locale.value).toBe("es");
    expect(t("nav.library")).toBe(es["nav.library"]);
    expect(localStorage.getItem("cinema-locale")).toBe("es");
    expect(document.documentElement.lang).toBe("es");
  });

  it("survives a throwing localStorage", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => useI18n().setLocale("es")).not.toThrow();
    spy.mockRestore();
  });
});

describe("detectLocale", () => {
  beforeEach(() => localStorage.clear());

  it("prefers a stored choice", () => {
    localStorage.setItem("cinema-locale", "en");
    vi.spyOn(navigator, "language", "get").mockReturnValue("es-CR");
    expect(detectLocale()).toBe("en");
    vi.restoreAllMocks();
  });

  it("falls back to the browser language", () => {
    const lang = vi.spyOn(navigator, "language", "get");
    lang.mockReturnValue("es-CR");
    expect(detectLocale()).toBe("es");
    lang.mockReturnValue("ES");
    expect(detectLocale()).toBe("es");
    lang.mockReturnValue("en-US");
    expect(detectLocale()).toBe("en");
    lang.mockReturnValue("fr-FR");
    expect(detectLocale()).toBe("en");
    vi.restoreAllMocks();
  });

  it("ignores junk in storage", () => {
    localStorage.setItem("cinema-locale", "klingon");
    vi.spyOn(navigator, "language", "get").mockReturnValue("es-MX");
    expect(detectLocale()).toBe("es");
    vi.restoreAllMocks();
  });
});
