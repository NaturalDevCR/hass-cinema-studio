<script setup lang="ts">
import type { Collection } from "@/api/types";
import { mdiFilmstripBox, mdiPencilOutline, mdiTrashCanOutline } from "@mdi/js";
import Icon from "./Icon.vue";
import EmptyState from "./EmptyState.vue";
import { useI18n } from "@/i18n";
import { useStudio } from "@/composables/useStudio";
import { resolveIcon } from "@/lib/icons";
defineProps<{ collections: Collection[]; pending: boolean; actingId?: string | null }>();
const emit = defineEmits<{
  create: [];
  edit: [value: Collection];
  remove: [value: Collection];
}>();
const { t } = useI18n();
const { procProfileById } = useStudio();
</script>
<template>
  <header class="mb-4 flex flex-wrap items-center justify-between gap-2">
    <h3 class="font-semibold">{{ t("organize.collections") }}</h3>
    <button type="button" class="btn-primary" :disabled="pending" @click="emit('create')">
      {{ t("organize.newCollection") }}
    </button>
  </header>
  <EmptyState
    v-if="!collections.length"
    :icon="mdiFilmstripBox"
    :title="t('organize.collections')"
    :description="t('organize.collections.empty')"
    ><button type="button" class="btn-primary" @click="emit('create')">
      {{ t("organize.newCollection") }}
    </button></EmptyState
  >
  <ul v-else class="space-y-3">
    <li
      v-for="collection in collections"
      :key="collection.id"
      class="rounded-lg border border-line bg-ground p-3"
      :class="{ 'opacity-60': !collection.enabled }"
    >
      <div class="flex min-w-0 items-center gap-2">
        <span class="size-2.5 shrink-0 rounded-full" :style="{ backgroundColor: collection.color }" />
        <Icon :path="resolveIcon(collection.icon)" :size="20" />
        <h4 class="min-w-0 break-words font-medium">{{ collection.name }}</h4>
        <span v-if="!collection.enabled" class="rounded bg-hover px-1 text-[10px] uppercase">{{ t("organize.disabled") }}</span>
      </div>
      <dl class="mt-3 space-y-1 text-sm">
        <div class="flex flex-wrap justify-between gap-1">
          <dt class="text-muted">{{ t("collection.mode") }}</dt>
          <dd>{{ t(`collection.mode.${collection.playback_mode}`) }}</dd>
        </div>
        <div class="flex flex-wrap justify-between gap-1">
          <dt class="text-muted">{{ t("collection.profile") }}</dt>
          <dd class="min-w-0 break-words">
            {{ procProfileById(collection.processing_profile_id)?.name ?? collection.processing_profile_id }}
          </dd>
        </div>
      </dl>
      <div class="mt-2 flex justify-end gap-1">
        <span class="mr-auto grid size-11 place-items-center">
          <span v-if="actingId === collection.id" role="status" :aria-label="t('common.loading')" class="size-4 animate-spin rounded-full border-2 border-muted border-t-transparent" />
        </span>
        <button
          type="button"
          class="btn-ghost size-11 p-0!"
          :disabled="pending"
          :aria-label="t('organize.edit', { name: collection.name })"
          @click="emit('edit', collection)"
        >
          <Icon :path="mdiPencilOutline" /></button
        ><button
          v-if="collection.id !== 'regular'"
          type="button"
          class="btn-ghost size-11 p-0! text-danger!"
          :disabled="pending"
          :aria-label="t('organize.delete', { name: collection.name })"
          @click="emit('remove', collection)"
        >
          <Icon :path="mdiTrashCanOutline" />
        </button>
      </div>
    </li>
  </ul>
</template>
