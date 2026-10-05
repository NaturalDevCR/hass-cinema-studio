<script setup lang="ts">
import type { Collection } from "@/api/types";
import Icon from "@/components/Icon.vue";
import { useI18n } from "@/i18n";
import { resolveIcon } from "@/lib/icons";
defineProps<{ collections: Collection[]; modelValue: string | null; counts: Record<string, number>; total: number }>();
const emit = defineEmits<{ "update:modelValue": [id: string | null] }>();
const { t } = useI18n();
</script>
<template><div role="group" :aria-label="t('library.collections')" class="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 py-1 md:mx-0 md:flex-wrap md:px-0"><button class="chip" :aria-pressed="modelValue === null" @click="emit('update:modelValue', null)">{{ t('common.all') }} <span>{{ total }}</span></button><button v-for="collection in collections" :key="collection.id" :data-test="`collection-${collection.id}`" class="chip" :aria-pressed="modelValue === collection.id" @click="emit('update:modelValue', collection.id)"><span class="size-2 rounded-full" :style="{ backgroundColor: collection.color }" /><Icon :path="resolveIcon(collection.icon)" :size="18" /> {{ collection.name }} <span>{{ counts[collection.id] ?? 0 }}</span><span class="rounded bg-hover px-1 text-[10px] uppercase">{{ t(`library.mode.${collection.playback_mode}`) }}</span></button></div></template>
