import { ref, type Ref } from "vue";
import { en } from "./en";
import { es } from "./es";

export type Locale = "es" | "en";
export type MessageKey = keyof typeof en;
export type MessageParams = Record<string, string | number>;

const STORAGE_KEY = "cinema-locale";
const catalogs: Record<Locale, Record<MessageKey, string>> = { en, es };

const isLocale = (value: unknown): value is Locale => value === "es" || value === "en";

/** Stored choice first, then the browser language ("es*" -> Spanish, anything else -> English). */
export function detectLocale(): Locale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (isLocale(stored)) return stored;
  } catch {
    // storage blocked (private mode, sandboxed iframe): fall through
  }
  const language = typeof navigator === "undefined" ? "" : navigator.language || "";
  return language.toLowerCase().startsWith("es") ? "es" : "en";
}

const locale = ref<Locale>(detectLocale());

function syncDocumentLanguage(value: Locale): void {
  if (typeof document !== "undefined") document.documentElement.lang = value;
}
syncDocumentLanguage(locale.value);

function setLocale(value: Locale): void {
  if (!isLocale(value)) return;
  locale.value = value;
  syncDocumentLanguage(value);
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // not persisted; the choice still applies for this session
  }
}

/** Looks a key up in the active language, replacing `{name}` placeholders. Reactive to locale changes. */
export function translate(key: MessageKey, params?: MessageParams): string {
  const text = catalogs[locale.value][key] ?? en[key] ?? key;
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match));
}

/** Bases `b` for which both `b.one` and `b.other` exist in the catalog. */
export type PluralKey = {
  [K in MessageKey]: K extends `${infer B}.one` ? (`${B}.other` extends MessageKey ? B : never) : never;
}[MessageKey];

/**
 * Picks `<base>.one` for exactly 1 and `<base>.other` for everything else (0, 2, 1.5, ...),
 * and fills `{n}` with the count. Both languages only need the one/other split.
 */
export function translatePlural(base: PluralKey, count: number, params: MessageParams = {}): string {
  return translate(`${base}.${count === 1 ? "one" : "other"}`, { ...params, n: count });
}

export function useI18n(): {
  t: typeof translate;
  tp: typeof translatePlural;
  locale: Ref<Locale>;
  setLocale: (value: Locale) => void;
} {
  return { t: translate, tp: translatePlural, locale, setLocale };
}
