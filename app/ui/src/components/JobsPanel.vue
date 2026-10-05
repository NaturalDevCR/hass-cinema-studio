<script setup lang="ts">
import { computed } from "vue";
import { useJobs } from "@/composables/useJobs";
import { useI18n } from "@/i18n";
import { formatDateTime } from "@/lib/format";
const MAX_JOBS = 30;
const { t, locale } = useI18n();
const { jobs, error, refresh } = useJobs();
const recent = computed(() =>
  [...jobs.value].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, MAX_JOBS),
);
</script>
<template>
  <section class="panel min-w-0 space-y-3" aria-labelledby="system-jobs-heading">
    <div class="flex items-center justify-between gap-2">
      <h3 id="system-jobs-heading" class="font-semibold">{{ t("jobs.heading") }}</h3>
      <button class="btn min-h-11!" @click="refresh">{{ t("common.refresh") }}</button>
    </div>
    <p v-if="error" role="alert" class="text-danger">{{ error }}</p>
    <ul class="space-y-2">
      <li v-for="job in recent" :key="job.id" class="rounded-lg bg-ground p-3 text-sm">
        <div class="flex justify-between gap-2">
          <span class="font-medium">{{ job.clip_title || t(`jobs.kind.${job.kind}`) }}</span>
          <span>{{ t(`jobs.status.${job.status}`) }}</span>
        </div>
        <progress v-if="job.status === 'running'" class="mt-2 w-full" max="1" :value="job.progress" />
        <p v-if="job.error" class="mt-1 text-danger">{{ job.error }}</p>
        <p class="mt-1 text-muted">{{ formatDateTime(job.created_at, locale) }}</p>
      </li>
      <li v-if="!recent.length" class="text-sm text-muted">{{ t("jobs.empty") }}</li>
    </ul>
  </section>
</template>
