<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { mdiUpload } from "@mdi/js";
import type { Collection } from "@/api/types";
import CollectionForm from "@/components/CollectionForm.vue";
import DropZone from "@/components/DropZone.vue";
import EmptyState from "@/components/EmptyState.vue";
import Sheet from "@/components/Sheet.vue";
import UploadRow from "@/components/UploadRow.vue";
import { useStudio } from "@/composables/useStudio";
import { useUpload } from "@/composables/useUpload";
import { useI18n } from "@/i18n";
const { t, tp } = useI18n();
const { collections, loaded, loading, refresh, error } = useStudio();
const { items, busy, add, start, remove, clearDone, retry } = useUpload();
const dropZone = ref<InstanceType<typeof DropZone> | null>(null);
const collection = ref("");
watch(
  collections,
  (values) => {
    if (!values.some((c) => c.id === collection.value)) {
      collection.value = (values.find((c) => c.id === "regular") ?? values[0])?.id ?? "";
    }
  },
  { immediate: true },
);
const defaultsSummary = computed(
  () => collections.value.find((c) => c.id === collection.value)?.name ?? t("upload.collection"),
);
const bar = ref<HTMLElement | null>(null);
const barHeight = ref(160);
watch(
  bar,
  (element, _, onCleanup) => {
    if (!element) return;
    const measure = () => { barHeight.value = element.getBoundingClientRect().height; };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    onCleanup(() => observer.disconnect());
  },
  { flush: "post" },
);
const defaultsOpen = ref(false);
const newCollection = ref(false);
const collectionBusy = ref(false);
const showBar = computed(
  () => busy.value || items.value.some((item) => ["pending", "uploading", "processing"].includes(item.status)),
);
const processingOnly = computed(
  () =>
    !busy.value &&
    items.value.some((i) => i.status === "processing") &&
    !items.value.some((i) => ["pending", "uploading"].includes(i.status)),
);
const count = computed(() => items.value.filter((i) => i.status === "pending").length);
const valid = computed(() => !!collection.value);
function upload(): void {
  if (!valid.value || busy.value || !loaded.value) return;
  // The batch default is the collection alone: titles and the rest are edited per clip afterwards.
  void start({ collection_id: collection.value });
}
function created(value: Collection): void {
  collection.value = value.id;
  newCollection.value = false;
}
</script>
<template>
  <section
    class="min-w-0 space-y-4"
    :style="{ paddingBottom: loaded && showBar ? `${barHeight + 24}px` : undefined }"
    aria-labelledby="upload-heading"
  >
    <h2 id="upload-heading" class="text-xl font-semibold">
      {{ t("upload.heading") }}
    </h2>
    <div v-if="!loaded" class="panel">
      <p v-if="loading" role="status">{{ t("common.loading") }}</p>
      <template v-else
        ><p v-if="error" role="alert" class="break-words text-danger">
          {{ error }}
        </p>
        <button class="btn-primary mt-3" @click="refresh()">
          {{ t("common.retry") }}
        </button></template
      >
    </div>
    <div v-else class="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
      <aside class="min-w-0">
        <div class="panel lg:sticky lg:top-20">
          <button
            type="button"
            class="flex min-h-11 w-full items-center justify-between gap-2 text-left font-medium lg:hidden"
            :aria-expanded="defaultsOpen"
            aria-controls="upload-defaults"
            @click="defaultsOpen = !defaultsOpen"
          >
            <span class="min-w-0">
              <span class="block">{{ t("upload.defaults") }}</span>
              <span
                v-if="!defaultsOpen"
                data-test="defaults-summary"
                class="block truncate text-xs font-normal text-muted"
                :title="defaultsSummary"
              >{{ defaultsSummary }}</span>
            </span>
            <span aria-hidden="true">{{ defaultsOpen ? "−" : "+" }}</span>
          </button>
          <h3 class="mb-2 hidden font-medium lg:block">
            {{ t("upload.defaults") }}
          </h3>
          <div id="upload-defaults" class="space-y-4" :class="defaultsOpen ? 'block' : 'hidden lg:block'">
            <p class="text-sm text-muted">{{ t("upload.defaults.hint") }}</p>
            <p v-if="!collections.length" class="text-sm text-warn">{{ t("upload.noCollection") }}</p>
            <div>
              <label for="upload-collection" class="mb-1.5 block text-sm font-medium">{{
                t("upload.collection")
              }}</label
              ><select id="upload-collection" v-model="collection" class="field">
                <option value="" disabled>
                  {{ t("upload.collection") }}
                </option>
                <option v-for="c in collections" :key="c.id" :value="c.id">
                  {{ c.name }}
                </option></select
              ><button type="button" class="btn-ghost mt-1 w-full" @click="newCollection = true">
                {{ t("organize.newCollection") }}
              </button>
            </div>
          </div>
        </div>
      </aside>
      <div class="min-w-0 space-y-4">
        <DropZone ref="dropZone" @files="add" />
        <div v-if="items.length" class="space-y-3">
          <div class="flex justify-end">
            <button
              type="button"
              class="btn-ghost"
              :disabled="!items.some((i) => i.status === 'done')"
              @click="clearDone"
            >
              {{ t("upload.clear") }}
            </button>
          </div>
          <ul class="space-y-2">
            <UploadRow v-for="item in items" :key="item.id" :item="item" @remove="remove" @retry="retry" />
          </ul>
        </div>
        <EmptyState v-else :icon="mdiUpload" :title="t('upload.empty.title')" :description="t('upload.empty.body')">
          <button type="button" class="btn-primary" @click="dropZone?.chooseFiles()">{{ t("upload.choose") }}</button>
        </EmptyState>
      </div>
    </div>
    <div
      v-if="loaded && showBar"
      ref="bar"
      data-test="upload-bar"
      class="fixed inset-x-0 bottom-[var(--tabbar-h)] z-30 border-t border-line bg-surface/95 px-4 pt-3 pb-3 md:pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur md:left-60 md:px-6"
    >
      <p v-if="!valid && count" role="alert" class="mx-auto mb-2 max-w-7xl text-sm text-warn">
        {{ t("upload.invalidDefaults") }}
      </p>
      <button
        type="button"
        class="btn-primary mx-auto flex w-full max-w-7xl"
        :disabled="busy || !count || !valid"
        @click="upload"
      >
        {{ busy ? t("upload.active") : processingOnly ? t("upload.processing") : tp("upload.start", count) }}
      </button>
    </div>
    <Sheet :open="newCollection" :title="t('organize.newCollection')" @close="!collectionBusy && (newCollection = false)"
      ><CollectionForm v-if="newCollection" @busy="collectionBusy = $event" @saved="created"
    /></Sheet>
  </section>
</template>
