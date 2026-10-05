<script setup lang="ts">
import { mdiCheckCircle, mdiClose, mdiReload, mdiFileVideoOutline } from "@mdi/js";
import type { UploadItem } from "@/composables/useUpload";
import { useI18n } from "@/i18n";
import { formatBytes } from "@/lib/format";
import Icon from "./Icon.vue";
const props = defineProps<{ item: UploadItem }>();
const emit = defineEmits<{ remove: [id: string]; retry: [id: string] }>();
const { t } = useI18n();
</script>
<template>
  <li class="rounded-panel border border-line bg-surface p-3">
    <div class="flex min-w-0 items-start gap-2">
      <span
        class="grid size-11 shrink-0 place-items-center rounded-lg bg-raised"
        :class="{ 'text-ok': item.status === 'done' }"
        ><Icon :path="item.status === 'done' ? mdiCheckCircle : mdiFileVideoOutline" :size="24"
      /></span>
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-medium" :title="item.file.name">
          {{ item.file.name }}
        </p>
        <p class="mt-1 text-xs text-muted">
          {{ formatBytes(item.file.size) }} ·
          <span role="status">{{ t(`upload.status.${item.status}`) }}</span>
        </p>
      </div>
      <button
        v-if="item.status === 'error' && !item.clipId && item.retryable"
        type="button"
        class="btn-ghost size-11 shrink-0 p-0!"
        :aria-label="t('upload.retry', { name: item.file.name })"
        @click="emit('retry', item.id)"
      >
        <Icon :path="mdiReload" />
      </button>
      <button
        v-if="item.status !== 'uploading'"
        type="button"
        class="btn-ghost size-11 shrink-0 p-0!"
        :aria-label="t('upload.remove', { name: item.file.name })"
        @click="emit('remove', item.id)"
      >
        <Icon :path="mdiClose" />
      </button>
    </div>
    <div
      v-if="item.status === 'uploading' || item.status === 'processing'"
      class="mt-3 h-1.5 overflow-hidden rounded-full bg-raised"
      role="progressbar"
      :aria-label="
        t('upload.progress', {
          name: item.file.name,
          n: Math.round(item.progress * 100),
        })
      "
      :aria-valuenow="item.status === 'uploading' ? Math.round(item.progress * 100) : undefined"
      aria-valuemin="0"
      aria-valuemax="100"
    >
      <div
        class="h-full rounded-full bg-accent transition-[width]"
        :class="{ 'animate-pulse': item.status === 'processing' }"
        :style="{ width: `${item.progress * 100}%` }"
      />
    </div>
    <p v-if="item.error" role="alert" class="mt-2 text-sm break-words text-danger">
      {{ item.error }}
    </p>
    <RouterLink
      v-if="item.status === 'done' && item.clipId"
      :to="{ name: 'clip', params: { id: item.clipId } }"
      class="btn mt-2 w-full"
      >{{ t("common.edit") }}</RouterLink
    >
  </li>
</template>
