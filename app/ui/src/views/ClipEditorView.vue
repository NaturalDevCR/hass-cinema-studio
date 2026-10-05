<script setup lang="ts">
import { useRouter } from "vue-router";
import Sheet from "@/components/Sheet.vue";
import { useI18n } from "@/i18n";

// Foundation placeholder: the clip editor lands with its own task. It already owns the
// full-screen sheet so the /clips/:id route opens and closes like the real editor will.
defineProps<{ id: string }>();
const { t } = useI18n();
const router = useRouter();
</script>

<template>
  <Sheet :open="true" :title="t('editor.title')" @close="router.push({ name: 'library' })" />
</template>
