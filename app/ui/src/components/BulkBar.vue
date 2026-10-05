<script setup lang="ts">
import { useI18n } from "@/i18n";
type Action = "move" | "enable" | "disable" | "normalize" | "rerender" | "delete";
defineProps<{ count: number; total: number; busy?: boolean }>(); const emit = defineEmits<{ action: [action: Action]; "select-all": []; done: [] }>(); const { t } = useI18n(); const actions: Action[] = ["move", "enable", "disable", "normalize", "rerender", "delete"];
</script>
<template><div role="toolbar" class="fixed inset-x-0 bottom-[var(--tabbar-h)] z-40 border-t border-line bg-raised p-3 md:left-60"><div class="flex flex-wrap items-center gap-2"><strong class="mr-auto">{{ t('library.selected', { n: count }) }}</strong><button class="btn" :disabled="count >= total" @click="emit('select-all')">{{ t('library.selectAll') }}</button><button v-for="action in actions" :key="action" :data-test="`action-${action}`" class="btn" :disabled="busy || !count" @click="emit('action', action)">{{ t(`library.action.${action}`) }}</button><button class="btn" @click="emit('done')">{{ t('common.close') }}</button></div></div></template>
