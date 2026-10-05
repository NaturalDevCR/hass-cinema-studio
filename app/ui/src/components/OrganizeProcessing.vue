<script setup lang="ts">
import type { ProcessingProfile } from "@/api/types";
import { mdiMovieCogOutline, mdiPencilOutline, mdiTrashCanOutline } from "@mdi/js";
import Icon from "./Icon.vue";
import EmptyState from "./EmptyState.vue";
import { useI18n } from "@/i18n";
import { formatLufs } from "@/lib/format";
defineProps<{ profiles: ProcessingProfile[]; pending: boolean; actingId?: string | null }>();
const emit = defineEmits<{
  create: [];
  edit: [value: ProcessingProfile];
  remove: [value: ProcessingProfile];
}>();
const { t } = useI18n();
function summary(profile: ProcessingProfile): string {
  const { video, loudness } = profile.settings;
  const loud =
    loudness.mode === "two_pass"
      ? t("processing.summary.twoPass", { lufs: formatLufs(loudness.integrated_lufs) })
      : t("processing.summary.noLoudness");
  return `${t("processing.summary", { w: video.width, h: video.height, fps: video.fps })} · ${loud}`;
}
</script>
<template>
  <header class="mb-4 flex flex-wrap items-center justify-between gap-2">
    <h3 class="font-semibold">{{ t("organize.processing") }}</h3>
    <button type="button" class="btn-primary" :disabled="pending" @click="emit('create')">
      {{ t("organize.newProcessing") }}
    </button>
  </header>
  <EmptyState
    v-if="!profiles.length"
    :icon="mdiMovieCogOutline"
    :title="t('organize.processing')"
    :description="t('organize.processing.empty')"
    ><button type="button" class="btn-primary" @click="emit('create')">
      {{ t("organize.newProcessing") }}
    </button></EmptyState
  >
  <ul v-else class="space-y-3">
    <li v-for="profile in profiles" :key="profile.id" class="rounded-lg border border-line bg-ground p-3">
      <h4 class="break-words font-medium">{{ profile.name }}</h4>
      <p class="mt-1 text-sm text-muted">{{ summary(profile) }}</p>
      <p v-if="profile.settings.intro_reference || profile.settings.outro_reference" class="mt-1 text-sm break-words text-muted">
        {{ [profile.settings.intro_reference, profile.settings.outro_reference].filter(Boolean).join(" · ") }}
      </p>
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
