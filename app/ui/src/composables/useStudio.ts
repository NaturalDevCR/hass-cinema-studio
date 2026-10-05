import { computed, ref } from "vue";
import { messageOf, ui } from "@/api/client";
import type {
  Asset,
  Clip,
  Collection,
  NormalizationProfile,
  ProcessingProfile,
  Season,
  Settings,
  State,
} from "@/api/types";

// Module-level singleton: every component sees the same lists, and a refresh
// from any view updates all of them.
const state = ref<State | null>(null);
const collections = ref<Collection[]>([]);
const seasons = ref<Season[]>([]);
const normProfiles = ref<NormalizationProfile[]>([]);
const procProfiles = ref<ProcessingProfile[]>([]);
const assets = ref<Asset[]>([]);
const clips = ref<Clip[]>([]);
// `loading` starts true: until the first refresh settles the lists are empty only because
// nothing has arrived yet, and views must not flash their empty state. `loaded` flips once,
// after the first successful refresh, and stays true (later refreshes keep the old data).
const loading = ref(true);
const loaded = ref(false);
const error = ref<string | null>(null);

const collectionIndex = computed(() => new Map(collections.value.map((c) => [c.id, c])));
const seasonIndex = computed(() => new Map(seasons.value.map((s) => [s.id, s])));
const normProfileIndex = computed(() => new Map(normProfiles.value.map((p) => [p.id, p])));
const procProfileIndex = computed(() => new Map(procProfiles.value.map((p) => [p.id, p])));

let inflight: Promise<void> | null = null;
let trailing: Promise<void> | null = null;
let settingsVersion = 0;

/** Apply the canonical PUT response before any pending refresh or queued save can use it. */
function applySettings(settings: Settings): void {
  settingsVersion += 1;
  if (state.value) state.value = { ...state.value, settings };
}

async function load(): Promise<void> {
  const version = settingsVersion;
  try {
    const [nextState, nextCollections, nextSeasons, nextNormProfiles, nextProcProfiles, nextAssets, nextClips] =
      await Promise.all([
        ui.state(),
        ui.collections.list(),
        ui.seasons.list(),
        ui.normProfiles.list(),
        ui.procProfiles.list(),
        ui.assets.list(),
        ui.clips.list(),
      ]);
    // Keep other refreshed fields (e.g. the rotated token), but a pre-PUT fetch must
    // never replace the successful PUT's settings, even if the follow-up fetch fails.
    state.value =
      version !== settingsVersion && state.value
        ? { ...nextState, settings: state.value.settings }
        : nextState;
    collections.value = nextCollections;
    seasons.value = nextSeasons;
    normProfiles.value = nextNormProfiles;
    procProfiles.value = nextProcProfiles;
    assets.value = nextAssets;
    clips.value = nextClips;
    loaded.value = true;
  } catch (cause) {
    error.value = messageOf(cause);
  }
}

function fetchStudio(): Promise<void> {
  loading.value = true;
  error.value = null;
  const run = load().finally(() => {
    loading.value = false;
    inflight = null;
  });
  inflight = run;
  return run;
}

/**
 * Reload everything in parallel. Normal callers share the current request; forced
 * callers wait for it and share one fresh request started after their mutation.
 * Never throws: failures land in `error`.
 */
function refresh(options: { force?: boolean } = {}): Promise<void> {
  const current = inflight;
  if (!current) return fetchStudio();
  if (!options.force) return current;
  trailing ??= current.then(() => {
    trailing = null;
    return inflight ?? fetchStudio();
  });
  return trailing;
}

let inflightClips: Promise<void> | null = null;
let trailingClips: Promise<void> | null = null;

async function loadClips(): Promise<void> {
  try {
    clips.value = await ui.clips.list();
    // Before the first full load `error` belongs to that failed load (its Retry banner): a
    // lightweight success, e.g. a job-completion poll, must not wipe it.
    if (loaded.value) error.value = null;
  } catch (cause) {
    error.value = messageOf(cause);
  }
}

function fetchClips(): Promise<void> {
  const run = loadClips().finally(() => {
    inflightClips = null;
  });
  inflightClips = run;
  return run;
}

/**
 * Lightweight reload of the clip list, used after jobs finish and after edits. A request already in flight may
 * have been sent before the caller's change landed, so a call made meanwhile waits for it and
 * then fetches once more; every caller that arrives in the meantime shares that single trailing
 * request. A success clears `error` once the studio has loaded.
 */
function refreshClips(): Promise<void> {
  const current = inflightClips;
  if (!current) return fetchClips();
  trailingClips ??= current.then(() => {
    trailingClips = null;
    // Another caller may already have started a (fresh enough) request in the gap.
    return inflightClips ?? fetchClips();
  });
  return trailingClips;
}

type Id = string | null | undefined;

export function useStudio() {
  return {
    state,
    collections,
    seasons,
    normProfiles,
    procProfiles,
    assets,
    clips,
    loading,
    loaded,
    error,
    refresh,
    applySettings,
    refreshClips,
    collectionById: (id: Id): Collection | undefined => (id ? collectionIndex.value.get(id) : undefined),
    seasonById: (id: Id): Season | undefined => (id ? seasonIndex.value.get(id) : undefined),
    normProfileById: (id: Id): NormalizationProfile | undefined =>
      id ? normProfileIndex.value.get(id) : undefined,
    procProfileById: (id: Id): ProcessingProfile | undefined =>
      id ? procProfileIndex.value.get(id) : undefined,
  };
}
