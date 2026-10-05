<script setup lang="ts">
import type { NormalizationProfile } from "@/api/types";
import { mdiPencilOutline, mdiTrashCanOutline, mdiTune } from "@mdi/js";
import Icon from "./Icon.vue";
import EmptyState from "./EmptyState.vue";
import { useI18n } from "@/i18n";
import { formatLufs, formatDb } from "@/lib/format";
defineProps<{ profiles: NormalizationProfile[]; pending: boolean; actingId?: string | null }>();
const emit = defineEmits<{
  create: [];
  edit: [value: NormalizationProfile];
  remove: [value: NormalizationProfile];
}>();
const { t } = useI18n();
</script>
<template>
  <header class="mb-4 flex flex-wrap items-center justify-between gap-2">
    <h3 class="font-semibold">{{ t("organize.profiles") }}</h3>
    <button type="button" class="btn-primary" :disabled="pending" @click="emit('create')">
      {{ t("organize.newProfile") }}
    </button>
  </header>
  <EmptyState
    v-if="!profiles.length"
    :icon="mdiTune"
    :title="t('organize.profiles')"
    :description="t('organize.profiles.empty')"
    ><button type="button" class="btn-primary" @click="emit('create')">
      {{ t("organize.newProfile") }}
    </button></EmptyState
  >
  <ul v-else class="space-y-3">
    <li v-for="profile in profiles" :key="profile.id" class="rounded-lg border border-line bg-ground p-3">
      <h4 class="break-words font-medium">{{ profile.name }}</h4>
      <dl class="mt-3 space-y-1 text-sm">
        <div class="flex flex-wrap justify-between gap-1">
          <dt class="text-muted">{{ t("profile.targetLufs") }}</dt>
          <dd class="tabular-nums">{{ formatLufs(profile.target_lufs) }}</dd>
        </div>
        <div class="flex flex-wrap justify-between gap-1">
          <dt class="text-muted">{{ t("profile.truePeak") }}</dt>
          <dd class="tabular-nums">{{ formatDb(profile.true_peak) }}</dd>
        </div>
        <div class="flex flex-wrap justify-between gap-1">
          <dt class="text-muted">{{ t("profile.lra") }}</dt>
          <dd class="tabular-nums">{{ profile.lra }}</dd>
        </div>
      </dl>
      <div class="mt-2 flex justify-end gap-1">
        <span class="mr-auto grid size-11 place-items-center">
          <span v-if="actingId === profile.id" role="status" :aria-label="t('common.loading')" class="size-4 animate-spin rounded-full border-2 border-muted border-t-transparent" />
        </span>
        <button
          type="button"
          class="btn-ghost size-11 p-0!"
          :disabled="pending"
          :aria-label="t('organize.edit', { name: profile.name })"
          @click="emit('edit', profile)"
        >
          <Icon :path="mdiPencilOutline" /></button
        ><button
          type="button"
          class="btn-ghost size-11 p-0! text-danger!"
          :disabled="pending"
          :aria-label="t('organize.delete', { name: profile.name })"
          @click="emit('remove', profile)"
        >
          <Icon :path="mdiTrashCanOutline" />
        </button>
      </div>
    </li>
  </ul>
</template>
