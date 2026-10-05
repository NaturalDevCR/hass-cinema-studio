<script setup lang="ts">
import type { LegacyReport } from "@/api/types";
import { useI18n } from "@/i18n";
import { formatDateTime } from "@/lib/format";
defineProps<{ report: LegacyReport | null }>();
const { t, locale } = useI18n();
type LegacyKey = "imported" | "queued" | "needsSource" | "skipped" | "missingAssets";
const sections = (report: LegacyReport): { key: LegacyKey; values: string[] }[] => [
  { key: "imported", values: report.imported },
  { key: "queued", values: report.queued_for_render },
  { key: "needsSource", values: report.needs_source },
  { key: "skipped", values: report.skipped.map((item) => `${item.clip_id}: ${item.reason}`) },
  { key: "missingAssets", values: report.missing_assets },
];
const label = (key: LegacyKey) =>
  t(`system.legacy.${key}` as
    | "system.legacy.imported"
    | "system.legacy.queued"
    | "system.legacy.needsSource"
    | "system.legacy.skipped"
    | "system.legacy.missingAssets");
</script>
<template>
  <section class="panel min-w-0 space-y-3" aria-labelledby="legacy-heading">
    <h3 id="legacy-heading" class="font-semibold">{{ t("system.legacyImport") }}</h3>
    <p>{{ t("system.legacyInstructions") }}</p>
    <template v-if="report">
      <p class="text-sm text-muted">
        {{ report.run_id }} · {{ formatDateTime(report.finished_at ?? report.started_at, locale) }}
      </p>
      <dl class="grid grid-cols-2 gap-2 text-sm">
        <div v-for="section in sections(report)" :key="section.key">
          <dt class="text-muted">{{ label(section.key) }}</dt>
          <dd>{{ section.values.length }}</dd>
        </div>
      </dl>
      <details v-for="section in sections(report)" :key="section.key" class="text-sm">
        <summary class="cursor-pointer">{{ label(section.key) }}</summary>
        <ul class="list-inside list-disc break-words text-muted">
          <li v-for="(value, index) in section.values" :key="`${index}-${value}`">{{ value }}</li>
        </ul>
      </details>
    </template>
    <p v-else class="text-sm text-muted">{{ t("system.legacyNone") }}</p>
  </section>
</template>
