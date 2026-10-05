<script setup lang="ts">
import { computed } from "vue";
import type { State } from "@/api/types";
import { formatBytes } from "@/lib/format";
import { useI18n } from "@/i18n";
const props = defineProps<{ storage: State["storage"]; reserveBytes: number }>();
const { t } = useI18n();
const used = computed(() => props.storage.originals_bytes + props.storage.renders_bytes + props.storage.retired_bytes + props.storage.work_bytes);
const total = computed(() => used.value + props.storage.free_bytes);
const usedPercent = computed(() => total.value > 0 ? Math.min(100, (used.value / total.value) * 100) : 0);
const reservePercent = computed(() => total.value > 0 ? Math.min(100, (props.reserveBytes / total.value) * 100) : 0);
const categories = computed(() => [
  { key: "originals", value: props.storage.originals_bytes },
  { key: "renders", value: props.storage.renders_bytes },
  { key: "retired", value: props.storage.retired_bytes },
  { key: "work", value: props.storage.work_bytes },
]);
</script>
<template>
  <section class="panel min-w-0 space-y-4" aria-labelledby="storage-heading">
    <h3 id="storage-heading" class="font-semibold">{{ t("system.storage") }}</h3>
    <div class="relative h-4 overflow-hidden rounded-full bg-ground" role="img" :aria-label="t('system.storageUsage', { used: formatBytes(used), free: formatBytes(storage.free_bytes) })">
      <div class="absolute inset-y-0 left-0 bg-accent" :style="{ width: `${usedPercent}%` }" />
      <div class="absolute inset-y-0 border-l-2 border-danger" :style="{ left: `${Math.max(0, 100 - reservePercent)}%` }" :title="t('system.reserve', { value: formatBytes(reserveBytes) })" />
    </div>
    <p class="text-sm text-muted">{{ t("system.freeSpace", { value: formatBytes(storage.free_bytes) }) }} · {{ t("system.reserve", { value: formatBytes(reserveBytes) }) }}</p>
    <dl class="grid grid-cols-2 gap-3 text-sm">
      <div v-for="item in categories" :key="item.key"><dt class="text-muted">{{ t(`system.${item.key}` as 'system.originals' | 'system.renders' | 'system.retired' | 'system.work') }}</dt><dd class="font-medium">{{ formatBytes(item.value) }}</dd></div>
    </dl>
    <p v-if="storage.network_fs" role="alert" class="text-sm text-warn">{{ t("system.networkFsWarning") }}</p>
  </section>
</template>
