<script setup lang="ts">
import { useStudio } from "@/composables/useStudio"; import { useI18n } from "@/i18n";
defineProps<{ modelValue: string | null }>(); const emit = defineEmits<{ "update:modelValue": [id: string | null] }>(); const { normProfiles } = useStudio(); const { t } = useI18n();
</script>
<template><label class="block space-y-1"><span>{{ t('library.profile') }}</span><select class="field w-full" :value="modelValue ?? ''" @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value || null)"><option value="">{{ t('common.none') }}</option><option v-for="profile in normProfiles" :key="profile.id" :value="profile.id">{{ profile.name }} ({{ profile.target_lufs }} LUFS)</option></select></label></template>
