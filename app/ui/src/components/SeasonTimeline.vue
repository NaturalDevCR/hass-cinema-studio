<script setup lang="ts">
import { computed, ref, useId } from "vue";
import type { Season } from "@/api/types";
import { messageOf, ui } from "@/api/client";
import { useI18n, type MessageKey } from "@/i18n";
import SeasonBadge from "./SeasonBadge.vue";
const props = withDefaults(defineProps<{ seasons: Season[]; showLegend?: boolean }>(), { showLegend: true });
const { t } = useI18n();
const id = useId();
const months = Array.from({ length: 12 }, (_, index) => index + 1);
const monthName = (month: number) => t(`month.${month}` as MessageKey);
// Use a leap year so February 29 has a distinct position, and include the final day.
const ordinal = (date: string) => {
  const [m, d] = date.split("-").map(Number);
  return (Date.UTC(2000, (m ?? 1) - 1, d ?? 1) - Date.UTC(2000, 0, 1)) / 86400000;
};
const rows = computed(() =>
  props.seasons
    .filter((s) => s.id !== "regular" && s.start && s.end)
    .map((season) => {
      const start = ordinal(season.start!);
      const end = ordinal(season.end!) + 1;
      return {
        season,
        segments:
          start < end
            ? [{ start, end }]
            : [
                { start, end: 366 },
                { start: 0, end },
              ],
      };
    }),
);
const today = new Date();
const todayDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
const todayPosition = (ordinal(todayDate.slice(5)) / 366) * 100;
const probe = ref("");
const result = ref<string | null>(null);
const pending = ref(false);
const error = ref<string | null>(null);
let request = 0;
async function resolve(): Promise<void> {
  const current = ++request;
  result.value = null;
  error.value = null;
  if (!probe.value) {
    pending.value = false;
    return;
  }
  pending.value = true;
  try {
    const response = await ui.seasons.resolve(probe.value);
    if (current === request) result.value = response.season_id;
  } catch (cause) {
    if (current === request) error.value = messageOf(cause);
  } finally {
    if (current === request) pending.value = false;
  }
}
const resolved = computed(() => props.seasons.find((s) => s.id === result.value));
</script>
<template>
  <div class="min-w-0 space-y-4">
    <div
      role="group"
      :aria-label="t('season.timeline')"
      class="relative rounded-lg border border-line bg-ground px-1 py-3"
    >
      <div class="relative h-6 text-[11px] text-muted">
        <span
          v-for="month in months"
          :key="month"
          data-test="month"
          class="absolute"
          :style="{
            left: `${(ordinal(`${String(month).padStart(2, '0')}-01`) / 366) * 100}%`,
          }"
          >{{ monthName(month) }}</span
        >
      </div>
      <div class="relative min-h-8 space-y-1">
        <div v-for="row in rows" :key="row.season.id" class="relative h-8 rounded bg-raised/50">
          <span
            v-for="(segment, index) in row.segments"
            :key="index"
            :data-season="row.season.id"
            role="img"
            :aria-hidden="index > 0 ? true : undefined"
            :aria-label="
              t('season.range', {
                name: row.season.name,
                start: row.season.start!,
                end: row.season.end!,
              })
            "
            class="absolute inset-y-1 min-w-[4px] rounded border border-white/20"
            :style="{
              left: `${(segment.start / 366) * 100}%`,
              width: `${((segment.end - segment.start) / 366) * 100}%`,
              backgroundColor: row.season.color,
            }"
          />
        </div>
        <span
          data-test="today"
          role="img"
          :aria-label="t('season.today', { date: todayDate })"
          :title="t('season.today', { date: todayDate })"
          class="pointer-events-none absolute inset-y-0 z-10 w-0.5 bg-ink"
          :style="{ left: `${todayPosition}%` }"
        />
      </div>
    </div>
    <ul v-if="showLegend && rows.length" class="space-y-2">
      <li v-for="row in rows" :key="row.season.id" class="flex flex-wrap items-center gap-2 text-xs text-muted">
        <SeasonBadge
          class="max-w-full [&>span:last-child]:min-w-0 [&>span:last-child]:truncate"
          :season="row.season"
        /><span>{{ row.season.start }} → {{ row.season.end }}</span>
      </li>
    </ul>
    <div>
      <label :for="id" class="mb-1.5 block text-sm font-medium">{{ t("season.probe") }}</label>
      <input :id="id" v-model="probe" type="date" class="field min-w-0" @change="resolve" />
      <div aria-live="polite" class="mt-2 min-h-6 text-sm">
        <span v-if="pending" role="status" class="text-muted">{{ t("common.loading") }}</span
        ><SeasonBadge v-else-if="resolved" :season="resolved" />
      </div>
      <p v-if="error" role="alert" class="text-sm break-words text-danger">
        {{ error }}
      </p>
    </div>
  </div>
</template>
