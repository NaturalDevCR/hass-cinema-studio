<script setup lang="ts">
import { mdiCog } from "@mdi/js";
import EmptyState from "@/components/EmptyState.vue";
import { useI18n } from "@/i18n";

// Foundation placeholder: connection, storage, GC and device panels land with their own task.
const { t } = useI18n();
</script>

<template>
  <section class="min-w-0 space-y-4" aria-labelledby="system-heading">
    <h2 id="system-heading" class="text-xl font-semibold">{{ t("system.heading") }}</h2>
    <EmptyState :icon="mdiCog" :title="t('system.empty.title')" :description="t('system.empty.body')" />
  </section>
</template>
