<script setup lang="ts">
import ConnectionPanel from "@/components/ConnectionPanel.vue";
import GcPanel from "@/components/GcPanel.vue";
import JobsPanel from "@/components/JobsPanel.vue";
import LegacyImportPanel from "@/components/LegacyImportPanel.vue";
import StoragePanel from "@/components/StoragePanel.vue";
import TestTargets from "@/components/TestTargets.vue";
import { useStudio } from "@/composables/useStudio";
import { useI18n } from "@/i18n";
const { t } = useI18n();
const { state, loaded, loading, error, refresh } = useStudio();
</script>

<template>
  <section class="min-w-0 space-y-4" aria-labelledby="system-heading">
    <h2 id="system-heading" class="text-xl font-semibold">{{ t("system.heading") }}</h2>
    <div v-if="!loaded" class="panel">
      <p v-if="loading" role="status">{{ t("common.loading") }}</p>
      <template v-else><p v-if="error" role="alert">{{ error }}</p><button class="btn-primary mt-3" @click="refresh()">{{ t("common.retry") }}</button></template>
    </div>
    <template v-else-if="state">
      <div class="grid min-w-0 gap-4 lg:grid-cols-2">
        <ConnectionPanel :state="state" />
        <StoragePanel :storage="state.storage" :reserve-bytes="state.settings.disk_reserve_bytes" />
        <GcPanel :state="state" :consumers="state.consumers" />
        <TestTargets :settings="state.settings" />
        <LegacyImportPanel :report="state.legacy_import" />
        <JobsPanel />
      </div>
    </template>
  </section>
</template>
