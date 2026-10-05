<script setup lang="ts">
import { computed, ref } from "vue";
import { ApiError, messageOf, ui } from "@/api/client";
import type { Collection, NormalizationProfile, ProcessingProfile, Season } from "@/api/types";
import AssetsPanel from "@/components/AssetsPanel.vue";
import CollectionForm from "@/components/CollectionForm.vue";
import OrganizeCollections from "@/components/OrganizeCollections.vue";
import OrganizeProcessing from "@/components/OrganizeProcessing.vue";
import OrganizeProfiles from "@/components/OrganizeProfiles.vue";
import OrganizeSeasons from "@/components/OrganizeSeasons.vue";
import ProcessingProfileForm from "@/components/ProcessingProfileForm.vue";
import ProfileForm from "@/components/ProfileForm.vue";
import SeasonForm from "@/components/SeasonForm.vue";
import Sheet from "@/components/Sheet.vue";
import { useConfirm } from "@/composables/useConfirm";
import { useStudio } from "@/composables/useStudio";
import { useToast } from "@/composables/useToast";
import { useI18n } from "@/i18n";
const { t } = useI18n();
const {
  collections, seasons, normProfiles, procProfiles, loaded, loading, refresh, error: loadError,
} = useStudio();
const tabs = ["collections", "seasons", "loudness", "processing", "assets"] as const;
type Tab = (typeof tabs)[number];
type Editor =
  | { kind: "collections"; value?: Collection }
  | { kind: "seasons"; value?: Season }
  | { kind: "loudness"; value?: NormalizationProfile }
  | { kind: "processing"; value?: ProcessingProfile };
type Removable = Exclude<Tab, "assets">;
const tab = ref<Tab>("collections");
const editor = ref<Editor | null>(null);
const formBusy = ref(false);
const pending = ref(false);
const acting = ref<{ kind: Tab; id: string } | null>(null);
const error = ref<string | null>(null);
const titles = {
  collections: ["organize.newCollection", "organize.editCollection"],
  seasons: ["organize.newSeason", "organize.editSeason"],
  loudness: ["organize.newProfile", "organize.editProfile"],
  processing: ["organize.newProcessing", "organize.editProcessing"],
} as const;
const title = computed(() => {
  const current = editor.value;
  return current ? t(titles[current.kind][current.value ? 1 : 0]) : "";
});
function open(value: Editor): void {
  if (!pending.value) {
    editor.value = value;
    error.value = null;
  }
}
function close(): void {
  if (!formBusy.value) editor.value = null;
}
function tabKey(event: KeyboardEvent): void {
  let index = tabs.indexOf(tab.value);
  if (event.key === "ArrowRight") index = (index + 1) % tabs.length;
  else if (event.key === "ArrowLeft") index = (index + tabs.length - 1) % tabs.length;
  else if (event.key === "Home") index = 0;
  else if (event.key === "End") index = tabs.length - 1;
  else return;
  event.preventDefault();
  tab.value = tabs[index]!;
  (event.currentTarget as HTMLElement).querySelector<HTMLButtonElement>(`#organize-tab-${tab.value}`)?.focus();
}
const removers: Record<Removable, (id: string) => Promise<void>> = {
  collections: (id) => ui.collections.remove(id),
  seasons: (id) => ui.seasons.remove(id),
  loudness: (id) => ui.normProfiles.remove(id),
  processing: (id) => ui.procProfiles.remove(id),
};
async function remove(kind: Removable, value: { id: string; name: string }): Promise<void> {
  if (pending.value || (kind === "seasons" && value.id === "regular") || (kind === "collections" && value.id === "regular")) return;
  const confirmed = await useConfirm().confirm({
    title: t("organize.delete.title", { name: value.name }),
    message: t("organize.delete.message"),
    danger: true,
    confirmLabel: t("common.delete"),
  });
  if (!confirmed || pending.value) return;
  pending.value = true;
  acting.value = { kind, id: value.id };
  error.value = null;
  try {
    await removers[kind](value.id);
    await refresh();
    useToast().push(t("organize.deleted"), "success");
  } catch (cause) {
    // The server's 409 for a collection is terse; say what to do about it.
    error.value = kind === "collections" && cause instanceof ApiError && cause.status === 409
      ? t("organize.collection.inUse")
      : messageOf(cause);
    useToast().push(error.value, "error");
  } finally {
    pending.value = false;
    acting.value = null;
  }
}
const actingId = (kind: Tab) => (acting.value?.kind === kind ? acting.value.id : null);
</script>
<template>
  <section class="min-w-0 space-y-4" aria-labelledby="organize-heading">
    <h2 id="organize-heading" class="text-xl font-semibold">
      {{ t("organize.heading") }}
    </h2>
    <div v-if="!loaded" class="panel">
      <p v-if="loading" role="status">{{ t("common.loading") }}</p>
      <template v-else
        ><p v-if="loadError" role="alert" class="break-words text-danger">
          {{ loadError }}
        </p>
        <button type="button" class="btn-primary mt-3" @click="refresh()">
          {{ t("common.retry") }}
        </button></template
      >
    </div>
    <template v-else>
      <div
        role="tablist"
        :aria-label="t('organize.heading')"
        class="no-scrollbar flex gap-1 overflow-x-auto rounded-lg border border-line bg-surface p-1"
        @keydown="tabKey"
      >
        <button
          v-for="key in tabs"
          :id="`organize-tab-${key}`"
          :key="key"
          type="button"
          role="tab"
          :aria-selected="tab === key"
          :aria-controls="`organize-${key}`"
          :tabindex="tab === key ? 0 : -1"
          class="min-h-11 min-w-fit flex-1 rounded-md px-3 text-sm font-medium whitespace-nowrap"
          :class="tab === key ? 'bg-accent-soft text-ink' : 'text-muted hover:bg-hover'"
          @click="tab = key"
        >
          {{ t(`organize.tab.${key}`) }}
        </button>
      </div>
      <p
        v-if="error"
        data-test="organize-error"
        class="rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm break-words text-danger"
      >
        {{ error }}
      </p>
      <div class="min-w-0" :aria-busy="pending">
        <section
          v-show="tab === 'collections'"
          id="organize-collections"
          role="tabpanel"
          aria-labelledby="organize-tab-collections"
          class="panel min-w-0"
        >
          <OrganizeCollections
            :collections="collections"
            :pending="pending"
            :acting-id="actingId('collections')"
            @create="open({ kind: 'collections' })"
            @edit="open({ kind: 'collections', value: $event })"
            @remove="remove('collections', $event)"
          />
        </section>
        <section
          v-show="tab === 'seasons'"
          id="organize-seasons"
          role="tabpanel"
          aria-labelledby="organize-tab-seasons"
          class="panel min-w-0"
        >
          <OrganizeSeasons
            :seasons="seasons"
            :pending="pending"
            :acting-id="actingId('seasons')"
            @create="open({ kind: 'seasons' })"
            @edit="open({ kind: 'seasons', value: $event })"
            @remove="remove('seasons', $event)"
          />
        </section>
        <section
          v-show="tab === 'loudness'"
          id="organize-loudness"
          role="tabpanel"
          aria-labelledby="organize-tab-loudness"
          class="panel min-w-0"
        >
          <OrganizeProfiles
            :profiles="normProfiles"
            :pending="pending"
            :acting-id="actingId('loudness')"
            @create="open({ kind: 'loudness' })"
            @edit="open({ kind: 'loudness', value: $event })"
            @remove="remove('loudness', $event)"
          />
        </section>
        <section
          v-show="tab === 'processing'"
          id="organize-processing"
          role="tabpanel"
          aria-labelledby="organize-tab-processing"
          class="panel min-w-0"
        >
          <OrganizeProcessing
            :profiles="procProfiles"
            :pending="pending"
            :acting-id="actingId('processing')"
            @create="open({ kind: 'processing' })"
            @edit="open({ kind: 'processing', value: $event })"
            @remove="remove('processing', $event)"
          />
        </section>
        <section
          v-show="tab === 'assets'"
          id="organize-assets"
          role="tabpanel"
          aria-labelledby="organize-tab-assets"
          class="panel min-w-0"
        >
          <AssetsPanel />
        </section>
      </div>
    </template>
    <Sheet :open="editor !== null" :title="title" @close="close">
      <CollectionForm
        v-if="editor?.kind === 'collections'"
        :collection="editor.value"
        @saved="editor = null"
        @busy="formBusy = $event"
      />
      <SeasonForm
        v-else-if="editor?.kind === 'seasons'"
        :season="editor.value"
        @saved="editor = null"
        @busy="formBusy = $event"
      />
      <ProfileForm
        v-else-if="editor?.kind === 'loudness'"
        :profile="editor.value"
        @saved="editor = null"
        @busy="formBusy = $event"
      />
      <ProcessingProfileForm
        v-else-if="editor?.kind === 'processing'"
        :profile="editor.value"
        @saved="editor = null"
        @busy="formBusy = $event"
      />
    </Sheet>
  </section>
</template>
