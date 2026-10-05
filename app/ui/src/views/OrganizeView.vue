<script setup lang="ts">
import { mdiShapeOutline } from "@mdi/js";
import EmptyState from "@/components/EmptyState.vue";
import { useI18n } from "@/i18n";

// Foundation placeholder: collections, seasons and profiles land with their own task.
const { t } = useI18n();
</script>

<template>
  <section class="min-w-0 space-y-4" aria-labelledby="organize-heading">
    <h2 id="organize-heading" class="text-xl font-semibold">{{ t("organize.heading") }}</h2>
    <EmptyState :icon="mdiShapeOutline" :title="t('organize.empty.title')" :description="t('organize.empty.body')" />
  </section>
</template>
