<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { api, filmstripUrl } from "@/api/client";
import type { Recipe } from "@/api/types";
import { snapTime, timeToX, xToTime } from "@/lib/timeline";
import { formatTimecode } from "@/lib/format";
import { useI18n } from "@/i18n";
const props = defineProps<{
  clipId: string;
  duration: number;
  fps: number | null;
  recipe: Recipe;
  position: number;
  bust?: string;
}>();
const emit = defineEmits<{
  trim: [start: number, end: number | null];
  seek: [time: number];
  invalid: [value: boolean];
}>();
const { t } = useI18n();
const strip = ref<HTMLElement | null>(null),
  count = ref(0),
  interval = ref(1),
  failed = ref(false);
const invalidStart = ref(false),
  invalidEnd = ref(false);
const startText = ref(formatTimecode(props.recipe.trim_start)),
  endText = ref(formatTimecode(props.recipe.trim_end ?? props.duration));
function parseTime(text: string): number | null {
  if (
    !/^(?:\d+(?:\.\d+)?|\d+:[0-5]\d:[0-5]\d(?:\.\d{1,3})?)$/.test(text.trim())
  )
    return null;
  return text
    .trim()
    .split(":")
    .map(Number)
    .reduce((n, part) => n * 60 + part, 0);
}
watch(
  () => props.recipe.trim_start,
  (value) => {
    if (parseTime(startText.value) !== value) {
      startText.value = formatTimecode(value);
      invalidStart.value = false;
    }
  },
);
watch(
  () => props.recipe.trim_end ?? props.duration,
  (value) => {
    if (parseTime(endText.value) !== value) {
      endText.value = formatTimecode(value);
      invalidEnd.value = false;
    }
  },
);
watch([invalidStart, invalidEnd], () =>
  emit("invalid", invalidStart.value || invalidEnd.value),
);
let generation = 0,
  dragging: "start" | "end" | null = null;
watch(
  () => [props.clipId, props.bust],
  async () => {
    const current = ++generation;
    count.value = 0;
    failed.value = false;
    try {
      const metadata = await api<{
        interval: number;
        count: number;
        width: number;
        height: number;
      }>(
        `api/ui/clips/${encodeURIComponent(props.clipId)}/filmstrip.json${props.bust ? `?v=${encodeURIComponent(props.bust)}` : ""}`,
      );
      if (current === generation) {
        count.value = Math.max(0, metadata.count);
        interval.value = metadata.interval;
      }
    } catch {
      if (current === generation) failed.value = true;
    }
  },
  { immediate: true },
);
// Everything (bar, filmstrip, handles) shares one time scale: percent of the strip width.
const percent = (n: number) => timeToX(n, props.duration, 100);
const span = (seconds: number) =>
  props.duration > 0 ? (seconds / props.duration) * 100 : 0;
const trimEnd = computed(() => props.recipe.trim_end ?? props.duration);
const trimRegion = computed(() => ({
  left: percent(props.recipe.trim_start),
  width: percent(trimEnd.value) - percent(props.recipe.trim_start),
}));
// Margins hug the trimmed region on the same scale, clipped at the clip edges.
const leadBlock = computed(() => {
  const right = percent(props.recipe.trim_start),
    left = Math.max(0, right - span(props.recipe.lead_in));
  return { left, width: right - left };
});
const tailBlock = computed(() => {
  const left = percent(trimEnd.value),
    right = Math.min(100, left + span(props.recipe.tail_out));
  return { left, width: right - left };
});
const box = (b: { left: number; width: number }) => ({
  left: b.left + '%',
  width: b.width + '%',
});
function pointerTime(e: PointerEvent) {
  const box = strip.value!.getBoundingClientRect();
  return Math.min(
    props.duration,
    Math.max(
      0,
      snapTime(
        xToTime(e.clientX - box.left, props.duration, box.width),
        props.fps,
      ),
    ),
  );
}
function change(edge: "start" | "end", n: number) {
  emit(
    "trim",
    edge === "start" ? n : props.recipe.trim_start,
    edge === "end" ? (n === props.duration ? null : n) : props.recipe.trim_end,
  );
}
function start(e: PointerEvent, edge: "start" | "end") {
  e.preventDefault();
  e.stopPropagation();
  dragging = edge;
  strip.value!.setPointerCapture(e.pointerId);
}
function move(e: PointerEvent) {
  if (dragging) change(dragging, pointerTime(e));
}
function key(e: KeyboardEvent, edge: "start" | "end") {
  if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key))
    return;
  e.preventDefault();
  const step =
    (props.fps && props.fps > 0 ? 1 / props.fps : 0.01) * (e.shiftKey ? 10 : 1);
  const value =
    edge === "start"
      ? props.recipe.trim_start
      : (props.recipe.trim_end ?? props.duration);
  change(
    edge,
    Math.max(
      0,
      Math.min(
        props.duration,
        snapTime(
          value + (["ArrowLeft", "ArrowDown"].includes(e.key) ? -step : step),
          props.fps,
        ),
      ),
    ),
  );
}
/** Drops pending text (valid or not) and shows the recipe's trim again. */
async function resync() {
  await nextTick();
  startText.value = formatTimecode(props.recipe.trim_start);
  endText.value = formatTimecode(trimEnd.value);
  invalidStart.value = false;
  invalidEnd.value = false;
}
defineExpose({ resync });
function input(e: Event, edge: "start" | "end") {
  const text = (e.target as HTMLInputElement).value.trim();
  if (edge === "start") startText.value = text;
  else endText.value = text;
  const value = parseTime(text);
  if (edge === "start") invalidStart.value = value === null;
  else invalidEnd.value = value === null;
  emit("invalid", invalidStart.value || invalidEnd.value);
  if (value !== null) change(edge, value);
}
</script>
<template>
  <section class="space-y-3" :aria-label="t('clipEditor.timeline')">
    <p class="text-xs text-muted">{{ t("clipEditor.timeline") }}</p>
    <div class="relative h-6 text-xs" aria-hidden="true">
      <span
        data-test="lead-block"
        class="absolute inset-y-0 overflow-hidden bg-black text-white"
        :style="box(leadBlock)"
        >{{ recipe.lead_in }} s</span
      >
      <span
        data-test="trim-region"
        class="absolute inset-y-0 bg-accent/30"
        :style="box(trimRegion)"
      />
      <span
        data-test="tail-block"
        class="absolute inset-y-0 overflow-hidden bg-black text-white"
        :style="box(tailBlock)"
        >{{ recipe.tail_out }} s</span
      >
    </div>
    <div
      ref="strip"
      data-test="strip"
      class="relative h-24 touch-none cursor-pointer rounded-md bg-ground"
      @pointerdown="emit('seek', pointerTime($event))"
      @pointermove="move"
      @pointerup="dragging = null"
      @pointercancel="dragging = null"
      @lostpointercapture="dragging = null"
    >
      <div
        class="absolute inset-0 flex overflow-hidden rounded"
        aria-hidden="true"
      >
        <img
          v-for="index in count"
          :key="index"
          :src="filmstripUrl(clipId, index - 1, bust)"
          alt=""
          class="min-w-0 h-full object-cover"
          :style="{
            width:
              (Math.min(interval, duration - (index - 1) * interval) /
                duration) *
                100 +
              '%',
          }"
        />
      </div>
      <div
        class="absolute inset-y-0 left-0 bg-black/70"
        :style="{ width: percent(recipe.trim_start) + '%' }"
      />
      <div
        class="absolute inset-y-0 right-0 bg-black/70"
        :style="{ width: 100 - percent(trimEnd) + '%' }"
      />
      <div
        class="pointer-events-none absolute inset-y-0 border-y-2 border-accent"
        aria-hidden="true"
        :style="{
          left: percent(recipe.trim_start) + '%',
          width: percent(trimEnd) - percent(recipe.trim_start) + '%',
        }"
      />
      <div
        class="absolute inset-y-0 w-0.5 bg-white pointer-events-none"
        :style="{ left: percent(position) + '%' }"
      />
      <button
        v-for="edge in ['start', 'end'] as const"
        :key="edge"
        class="absolute inset-y-0 z-10 grid w-5 cursor-ew-resize place-items-center bg-accent text-accent-ink"
        :class="
          edge === 'start'
            ? 'rounded-l-md'
            : '-translate-x-full rounded-r-md'
        "
        role="slider"
        :aria-label="
          t(edge === 'start' ? 'clipEditor.trimStart' : 'clipEditor.trimEnd')
        "
        :aria-valuemin="0"
        :aria-valuemax="duration"
        :aria-valuenow="
          edge === 'start' ? recipe.trim_start : (recipe.trim_end ?? duration)
        "
        :style="{
          left:
            percent(
              edge === 'start'
                ? recipe.trim_start
                : (recipe.trim_end ?? duration),
            ) + '%',
        }"
        @pointerdown="start($event, edge)"
        @keydown="key($event, edge)"
      >
        <span class="h-8 w-0.5 rounded bg-black/40" aria-hidden="true" />
      </button>
    </div>
    <p v-if="failed" class="text-xs text-muted">
      {{ t("clipEditor.filmstripError") }}
    </p>
    <div class="grid grid-cols-2 gap-3">
      <label
        >{{ t("clipEditor.trimStart")
        }}<input
          data-test="trim-start"
          class="field w-full font-mono"
          :value="startText"
          :aria-invalid="invalidStart"
          @input="input($event, 'start')" /></label
      ><label
        >{{ t("clipEditor.trimEnd")
        }}<input
          data-test="trim-end"
          class="field w-full font-mono"
          :value="endText"
          :aria-invalid="invalidEnd"
          @input="input($event, 'end')"
      /></label>
    </div>
    <p v-if="invalidStart || invalidEnd" role="alert" class="text-danger">
      {{ t("clipEditor.invalidTime") }}
    </p>
  </section>
</template>
