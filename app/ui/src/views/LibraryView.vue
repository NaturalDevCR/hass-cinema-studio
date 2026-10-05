<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { mdiFilmstripBox } from "@mdi/js";
import { ui, messageOf } from "@/api/client";
import type { ClipStatus } from "@/api/types";
import BulkBar from "@/components/BulkBar.vue";
import ClipCard from "@/components/ClipCard.vue";
import CollectionChips from "@/components/CollectionChips.vue";
import CustomOrderList from "@/components/CustomOrderList.vue";
import EmptyState from "@/components/EmptyState.vue";
import LoudnessStrip from "@/components/LoudnessStrip.vue";
import ProfilePicker from "@/components/ProfilePicker.vue";
import Sheet from "@/components/Sheet.vue";
import { useConfirm } from "@/composables/useConfirm";
import { usePlayer } from "@/composables/usePlayer";
import { useStudio } from "@/composables/useStudio";
import { useToast } from "@/composables/useToast";
import { filterClips } from "@/lib/filters";
import { useI18n } from "@/i18n";
const { t } = useI18n(); const route = useRoute(); const router = useRouter();
const { clips, collections, seasons, normProfiles, loaded, refreshClips, seasonById } = useStudio();
const { confirm } = useConfirm(); const toast = useToast(); const player = usePlayer();
const selectedCollection = ref<string | null>(null); const query = ref(""); const seasonId = ref<string | null>(null); const status = ref<ClipStatus | null>(null);
const selected = ref<string[]>([]); const busy = ref(false); const sheet = ref<"move" | "normalize" | "level" | null>(null); const profileId = ref<string | null>(null); const destination = ref(""); const actionError = ref("");
let debounce: ReturnType<typeof setTimeout> | undefined; let searchPending = false;
watch(() => route.query, q => { selectedCollection.value = typeof q.collection === "string" ? q.collection : null; if (!searchPending) query.value = typeof q.q === "string" ? q.q : ""; seasonId.value = typeof q.season === "string" ? q.season : null; status.value = ["processing", "ready", "rendering", "failed"].includes(String(q.status)) ? q.status as ClipStatus : null; }, { immediate: true });
const seasonCollectionId = computed(() => seasonId.value ? seasonById(seasonId.value)?.collection_id ?? null : null);
const filtered = computed(() => filterClips(clips.value, { collectionId: selectedCollection.value, seasonId: seasonId.value, seasonCollectionId: seasonCollectionId.value, query: query.value, status: status.value }));
const counts = computed(() => Object.fromEntries(collections.value.map(c => [c.id, clips.value.filter(x => x.collection_id === c.id).length])));
const selectedCollectionModel = computed(() => collections.value.find(c => c.id === selectedCollection.value));
const collectionClips = computed(() => selectedCollection.value ? clips.value.filter(c => c.collection_id === selectedCollection.value) : []);
const seasonOptions = computed(() => [{ id: "", name: t("common.all") }, ...seasons.value]);
const statuses: (ClipStatus | "")[] = ["", "ready", "processing", "rendering", "failed"];
// Typed text is the source of truth while the debounce is pending: other filters merge it into
// their URL update, and the route watcher never copies a stale `q` back over the input.
function updateQuery(patch: Record<string, string | null>) {
  const q = { ...route.query };
  if (searchPending) { clearTimeout(debounce); searchPending = false; patch = { q: query.value || null, ...patch }; }
  for (const [key, value] of Object.entries(patch)) { if (value) q[key] = value; else delete q[key]; }
  void router.replace({ query: q });
}
function updateSearch(value: string) { query.value = value; searchPending = true; clearTimeout(debounce); debounce = setTimeout(() => updateQuery({ q: query.value || null }), 150); }
function chooseCollection(value: string | null) { selectedCollection.value = value; updateQuery({ collection: value }); }
function toggleSelect(id: string) { selected.value = selected.value.includes(id) ? selected.value.filter(x => x !== id) : [...selected.value, id]; }
function open(id: string) { void router.push({ name: "clip", params: { id }, query: route.query }); }
function play(_id: string) { /* ClipCard owns the shared video element and inline host. */ }
async function applyProfile(ids: string[], profile: string | null) { if (profile) await ui.normProfiles.apply(profile, { clip_ids: ids }); else await ui.clips.bulk({ ids, set: { profile_id: null } }); }
async function runAction(action: string) {
  actionError.value = "";
  if (action === "move") { destination.value = collections.value[0]?.id ?? ""; sheet.value = "move"; return; }
  if (action === "normalize") { profileId.value = null; sheet.value = "normalize"; return; }
  if (action === "delete" && !(await confirm({ title: t("library.deleteTitle"), message: t("library.deleteMessage", { n: selected.value.length }), danger: true }))) return;
  busy.value = true;
  try {
    if (action === "delete") { for (const id of selected.value) await ui.clips.remove(id); }
    else if (action === "rerender") { for (const id of selected.value) await ui.clips.rerender(id); }
    else await ui.clips.bulk({ ids: selected.value, set: { enabled: action === "enable" ? true : action === "disable" ? false : undefined } });
    selected.value = []; await refreshClips(); toast.push(t("library.updated"), "success");
  } catch (cause) { actionError.value = messageOf(cause); } finally { busy.value = false; }
}
async function commitSheet() {
  busy.value = true; actionError.value = "";
  try {
    if (sheet.value === "move") await ui.clips.bulk({ ids: selected.value, set: { collection_id: destination.value } });
    else if (sheet.value === "normalize") await applyProfile(selected.value, profileId.value);
    else if (sheet.value === "level" && selectedCollection.value && profileId.value) await ui.normProfiles.apply(profileId.value, { collection_id: selectedCollection.value });
    sheet.value = null; selected.value = []; await refreshClips();
  } catch (cause) { actionError.value = messageOf(cause); } finally { busy.value = false; }
}
function levelCollection() { profileId.value = normProfiles.value[0]?.id ?? null; sheet.value = "level"; }
watch(filtered, value => { selected.value = selected.value.filter(id => value.some(c => c.id === id)); });
onBeforeUnmount(() => { clearTimeout(debounce); player.stop(); });
</script>
<template>
  <section data-test="library" class="min-w-0 space-y-4" aria-labelledby="library-heading">
    <h2 id="library-heading" class="sr-only">{{ t("library.heading") }}</h2>
    <template v-if="loaded">
      <template v-if="clips.length">
        <CollectionChips :collections="collections" :model-value="selectedCollection" :counts="counts" :total="clips.length" @update:model-value="chooseCollection" />
        <div class="flex flex-col gap-2 sm:flex-row"><input class="field min-w-0 flex-1" type="search" :value="query" :placeholder="t('library.search')" @input="updateSearch(($event.target as HTMLInputElement).value)" /><select class="field" :value="seasonId ?? ''" :aria-label="t('library.season')" @change="seasonId = ($event.target as HTMLSelectElement).value || null; selectedCollection = null; updateQuery({ season: seasonId, collection: null })"><option v-for="season in seasonOptions" :key="season.id" :value="season.id">{{ season.name }}</option></select><select class="field" :value="status ?? ''" :aria-label="t('library.status')" @change="status = (($event.target as HTMLSelectElement).value || null) as ClipStatus | null; updateQuery({ status })"><option v-for="value in statuses" :key="value" :value="value">{{ value ? t(`status.${value}`) : t('library.anyStatus') }}</option></select></div>
        <LoudnessStrip v-if="selectedCollectionModel" :clips="collectionClips" :collection-name="selectedCollectionModel.name" @level="levelCollection" />
        <CustomOrderList v-if="selectedCollectionModel?.playback_mode === 'custom'" :collection-id="selectedCollectionModel.id" :clips="collectionClips" />
        <div v-if="filtered.length" class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"><ClipCard v-for="clip in filtered" :key="clip.id" :clip="clip" :selected="selected.includes(clip.id)" :selecting="selected.length > 0" :playing="player.currentId.value === clip.id && player.playing.value" @open="open" @play="play" @select="toggleSelect" /></div>
        <EmptyState v-else :icon="mdiFilmstripBox" :title="t('library.noMatches')" :description="t('library.clearFilters')"><button class="btn" @click="selectedCollection = null; query = ''; seasonId = null; status = null; void router.replace({ query: {} })">{{ t('library.clear') }}</button></EmptyState>
      </template>
      <EmptyState v-else :icon="mdiFilmstripBox" :title="t('library.empty.title')" :description="t('library.empty.body')"><RouterLink class="btn" to="/upload">{{ t('library.upload') }}</RouterLink><RouterLink class="btn" to="/system?section=import">{{ t('library.import') }}</RouterLink></EmptyState>
    </template>
    <BulkBar v-if="selected.length" :count="selected.length" :total="filtered.length" :busy="busy" @action="runAction" @done="selected = []" @select-all="selected = filtered.map(c => c.id)" />
    <Sheet :open="sheet !== null" :title="sheet === 'move' ? t('library.move') : sheet === 'level' ? t('library.level') : t('library.normalize')" @close="sheet = null"><label v-if="sheet === 'move'" class="block">{{ t('library.destination') }}<select v-model="destination" class="field mt-2 w-full"><option v-for="c in collections" :key="c.id" :value="c.id">{{ c.name }}</option></select></label><ProfilePicker v-else-if="sheet" v-model="profileId" /><p v-if="actionError" role="alert" class="mt-3 text-danger">{{ actionError }}</p><template #footer><button class="btn-primary w-full" :disabled="busy || (sheet === 'move' && !destination)" @click="commitSheet">{{ t('common.confirm') }}</button></template></Sheet>
  </section>
  <RouterView />
</template>
