<script setup lang="ts">
import type { Season } from "@/api/types";
import { mdiPencilOutline, mdiTrashCanOutline, mdiCalendarStar } from "@mdi/js";
import Icon from "./Icon.vue";
import EmptyState from "./EmptyState.vue";
import { useI18n } from "@/i18n";
import SeasonTimeline from "./SeasonTimeline.vue";
import SeasonBadge from "./SeasonBadge.vue";
defineProps<{ seasons: Season[]; pending: boolean; actingId?: string | null }>();
const emit = defineEmits<{
  create: [];
  edit: [value: Season];
  remove: [value: Season];
}>();
const { t } = useI18n();
</script>
<template>
  <header class="mb-4 flex flex-wrap items-center justify-between gap-2">
    <h3 class="font-semibold">{{ t("organize.seasons") }}</h3>
    <button type="button" class="btn-primary" :disabled="pending" @click="emit('create')">
      {{ t("organize.newSeason") }}
    </button>
  </header>
  <SeasonTimeline :seasons="seasons" :show-legend="false" />
  <EmptyState
    v-if="!seasons.length"
    :icon="mdiCalendarStar"
    :title="t('organize.seasons')"
    :description="t('organize.seasons.empty')"
    ><button type="button" class="btn-primary" @click="emit('create')">
      {{ t("organize.newSeason") }}
    </button></EmptyState
  >
  <ul v-else class="mt-4 space-y-2">
    <li v-for="season in seasons" :key="season.id" class="rounded-lg border border-line bg-ground p-3">
      <div class="min-w-0">
        <SeasonBadge class="max-w-full [&>span:last-child]:min-w-0 [&>span:last-child]:truncate" :season="season" />
        <p v-if="season.start" class="mt-2 text-xs text-muted">
          {{ season.start }} → {{ season.end }} · {{ t("season.priority") }}
          {{ season.priority }}
        </p>
      </div>
      <div class="mt-1 flex justify-end gap-1">
        <span class="mr-auto grid size-11 place-items-center">
          <span v-if="actingId === season.id" role="status" :aria-label="t('common.loading')" class="size-4 animate-spin rounded-full border-2 border-muted border-t-transparent" />
        </span>
        <button
          type="button"
          class="btn-ghost size-11 p-0!"
          :disabled="pending"
          :aria-label="t('organize.edit', { name: season.name })"
          @click="emit('edit', season)"
        >
          <Icon :path="mdiPencilOutline" /></button
        ><button
          v-if="season.id !== 'regular'"
          type="button"
          class="btn-ghost size-11 p-0! text-danger!"
          :disabled="pending"
          :aria-label="t('organize.delete', { name: season.name })"
          @click="emit('remove', season)"
        >
          <Icon :path="mdiTrashCanOutline" />
        </button>
      </div>
    </li>
  </ul>
</template>
