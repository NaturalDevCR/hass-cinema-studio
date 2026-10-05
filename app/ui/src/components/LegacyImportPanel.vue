<script setup lang="ts">
import type { LegacyReport } from "@/api/types";
import { useI18n } from "@/i18n";
const props = defineProps<{ report: LegacyReport | null }>();
const { t } = useI18n();
const counts = (report: LegacyReport) => [
  ["imported", report.imported.length], ["queued", report.queued_for_render.length],
  ["needsSource", report.needs_source.length], ["skipped", report.skipped.length], ["missingAssets", report.missing_assets.length],
] as const;
const details = (report: LegacyReport) => [
  { key: "imported", values: report.imported },
  { key: "queued", values: report.queued_for_render },
  { key: "needsSource", values: report.needs_source },
  { key: "skipped", values: report.skipped.map((item) => `${item.clip_id}: ${item.reason}`) },
  { key: "missingAssets", values: report.missing_assets },
] as const;
</script>
<template>
  <section class="panel min-w-0 space-y-3" aria-labelledby="legacy-heading">
    <h3 id="legacy-heading" class="font-semibold">{{ t("system.legacyImport") }}</h3>
    <p>{{ t("system.legacyInstructions") }}</p>
    <template v-if="report"><p class="text-sm text-muted">{{ report.run_id }} · {{ report.finished_at ?? report.started_at }}</p><dl class="grid grid-cols-2 gap-2 text-sm"><div v-for="[key, value] in counts(report)" :key="key"><dt class="text-muted">{{ t(`system.legacy.${key}`) }}</dt><dd>{{ value }}</dd></div></dl>
      <details v-for="item in details(report)" :key="item.key" class="text-sm"><summary class="cursor-pointer">{{ t(`system.legacy.${item.key}` as 'system.legacy.imported' | 'system.legacy.queued' | 'system.legacy.needsSource' | 'system.legacy.skipped' | 'system.legacy.missingAssets') }}</summary><ul class="list-inside list-disc break-words text-muted"><li v-for="value in item.values" :key="value">{{ value }}</li></ul></details>
    </template><p v-else class="text-sm text-muted">{{ t("system.legacyNone") }}</p>
  </section>
</template>
