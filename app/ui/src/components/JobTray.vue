<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { mdiAlertCircleOutline, mdiCheckCircleOutline, mdiLoading, mdiProgressCheck } from "@mdi/js";
import type { Job } from "@/api/types";
import Icon from "@/components/Icon.vue";
import { useJobs } from "@/composables/useJobs";
import { useI18n } from "@/i18n";

const { t } = useI18n();
const { jobs, active } = useJobs();

const MAX_ROWS = 12;
const open = ref(false);
const root = ref<HTMLElement | null>(null);
const trigger = ref<HTMLButtonElement | null>(null);
const panelId = "job-tray-panel";

const rows = computed(() => jobs.value.slice(0, MAX_ROWS));
const summary = computed(() =>
  active.value.length ? t("jobs.active", { n: active.value.length }) : t("jobs.idle"),
);

const isRunning = (job: Job) => job.status === "queued" || job.status === "running";
const percent = (job: Job) => Math.round(Math.min(1, Math.max(0, job.progress)) * 100);
const tone = (job: Job) =>
  job.status === "failed" ? "text-danger" : job.status === "done" ? "text-ok" : "text-amber-200";

function close(returnFocus = false): void {
  open.value = false;
  if (returnFocus) trigger.value?.focus();
}

function onKeydown(event: KeyboardEvent): void {
  if (open.value && event.key === "Escape") close(true);
}

function onPointerDown(event: Event): void {
  if (open.value && root.value && !root.value.contains(event.target as Node)) close();
}

onMounted(() => {
  document.addEventListener("keydown", onKeydown);
  document.addEventListener("pointerdown", onPointerDown);
});
onBeforeUnmount(() => {
  document.removeEventListener("keydown", onKeydown);
  document.removeEventListener("pointerdown", onPointerDown);
});
</script>

<template>
  <div ref="root" class="relative">
    <button
      ref="trigger"
      type="button"
      class="btn-ghost relative min-w-11 px-2.5 md:px-3"
      :aria-expanded="open"
      :aria-controls="panelId"
      :aria-label="`${t('jobs.tray.label')}: ${summary}`"
      @click="open = !open"
    >
      <Icon :path="active.length ? mdiLoading : mdiProgressCheck" :class="{ 'animate-spin': active.length }" />
      <span class="hidden text-sm md:inline">{{ summary }}</span>
      <span
        v-if="active.length"
        data-test="badge"
        aria-hidden="true"
        class="absolute -top-0.5 -right-0.5 grid h-5 min-w-5 place-items-center rounded-full bg-accent-strong px-1 text-xs leading-none font-bold text-accent-ink md:hidden"
      >
        {{ active.length }}
      </span>
    </button>

    <div
      v-if="open"
      :id="panelId"
      role="region"
      :aria-label="t('jobs.title')"
      class="absolute top-full right-0 z-40 mt-2 w-[min(24rem,calc(100vw-2rem))] rounded-panel border border-line bg-raised p-2 shadow-2xl"
    >
      <p v-if="!jobs.length" class="px-3 py-5 text-center text-sm text-muted">{{ t("jobs.empty") }}</p>
      <ul v-else class="max-h-[60dvh] space-y-1 overflow-y-auto overscroll-contain">
        <li v-for="job in rows" :key="job.id" class="rounded-lg px-3 py-2" :class="{ 'opacity-75': !isRunning(job) }">
          <div class="flex items-center justify-between gap-3">
            <span class="min-w-0 truncate text-sm font-medium" :title="job.clip_title">{{ job.clip_title }}</span>
            <span class="inline-flex shrink-0 items-center gap-1 text-xs font-medium" :class="tone(job)">
              <Icon
                v-if="job.status === 'failed'"
                :path="mdiAlertCircleOutline"
                :size="14"
              />
              <Icon v-else-if="job.status === 'done'" :path="mdiCheckCircleOutline" :size="14" />
              {{ t(`jobs.status.${job.status}`) }}
            </span>
          </div>
          <p class="text-xs text-muted">{{ t(`jobs.kind.${job.kind}`) }}</p>
          <div
            v-if="isRunning(job)"
            role="progressbar"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-valuenow="percent(job)"
            :aria-label="t('jobs.progress', { title: job.clip_title, n: percent(job) })"
            class="mt-2 h-1.5 overflow-hidden rounded-full bg-hover"
          >
            <div class="h-full rounded-full bg-accent transition-[width] duration-500" :style="{ width: `${percent(job)}%` }" />
          </div>
          <p v-if="job.error" class="mt-1 text-xs break-words text-danger">{{ job.error }}</p>
        </li>
      </ul>
    </div>
  </div>
</template>
