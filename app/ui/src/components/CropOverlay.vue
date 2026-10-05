<script setup lang="ts">
import { computed, ref } from "vue";
import { aspectLock, clampCrop, displayFromCrop, type Rect } from "@/lib/crop";
import { useI18n } from "@/i18n";
const props = defineProps<{
  modelValue: Rect | null;
  width: number;
  height: number;
  locked: boolean;
}>();
const emit = defineEmits<{ "update:modelValue": [Rect | null] }>();
const { t } = useI18n();
const host = ref<HTMLElement | null>(null);
const rect = computed(
  () => props.modelValue ?? { x: 0, y: 0, w: props.width, h: props.height },
);
// Percent of the displayed frame, so the box tracks the video at any size.
const shown = computed(() =>
  displayFromCrop(rect.value, 100, 100, props.width, props.height),
);
const dims = computed(() => {
  const r = shown.value;
  return [
    { top: 0, left: 0, width: 100, height: r.y },
    { top: r.y + r.h, left: 0, width: 100, height: 100 - r.y - r.h },
    { top: r.y, left: 0, width: r.x, height: r.h },
    { top: r.y, left: r.x + r.w, width: 100 - r.x - r.w, height: r.h },
  ];
});
const corners = ["nw", "ne", "sw", "se"] as const;
let drag: {
  id: number;
  x: number;
  y: number;
  r: Rect;
  corner: (typeof corners)[number] | null;
  displayW: number;
  displayH: number;
} | null = null;
function start(e: PointerEvent, corner: (typeof corners)[number] | null) {
  const box = host.value?.getBoundingClientRect();
  if (!box?.width || !box.height) return;
  e.preventDefault();
  e.stopPropagation();
  host.value!.setPointerCapture(e.pointerId);
  drag = {
    id: e.pointerId,
    x: e.clientX,
    y: e.clientY,
    r: { ...rect.value },
    corner,
    displayW: box.width,
    displayH: box.height,
  };
}
function move(e: PointerEvent) {
  if (!drag || drag.id !== e.pointerId) return;
  const dx = ((e.clientX - drag.x) * props.width) / drag.displayW,
    dy = ((e.clientY - drag.y) * props.height) / drag.displayH;
  let r = { ...drag.r };
  if (!drag.corner) {
    r.x += dx;
    r.y += dy;
  } else {
    const west = drag.corner.endsWith("w"),
      north = drag.corner.startsWith("n");
    const w = Math.max(64, r.w + (west ? -dx : dx)),
      h = Math.max(64, r.h + (north ? -dy : dy));
    r = { x: west ? r.x + r.w - w : r.x, y: north ? r.y + r.h - h : r.y, w, h };
    if (props.locked) r = lockedRect(r, drag.corner);
  }
  emit("update:modelValue", clampCrop(r, props.width, props.height));
}
function lockedRect(r: Rect, corner: (typeof corners)[number]): Rect {
  // Fit the ratio before rounding so clamping at the source edges cannot stretch it.
  const aspect = 16 / 9,
    h = Math.min(props.height, Math.max(64, r.w / aspect));
  const w = Math.min(props.width, h * aspect);
  const resized = { ...r, x: corner.endsWith("w") ? r.x + r.w - w : r.x, w };
  return aspectLock(resized, aspect, corner);
}
function end() {
  drag = null;
}
function nudge(e: KeyboardEvent, corner: (typeof corners)[number]) {
  if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key))
    return;
  e.preventDefault();
  const r = { ...rect.value },
    delta = e.shiftKey ? 20 : 2;
  const dx =
    e.key === "ArrowLeft" ? -delta : e.key === "ArrowRight" ? delta : 0;
  const dy = e.key === "ArrowUp" ? -delta : e.key === "ArrowDown" ? delta : 0;
  if (corner.endsWith("w")) {
    r.x += dx;
    r.w -= dx;
  } else r.w += dx;
  if (corner.startsWith("n")) {
    r.y += dy;
    r.h -= dy;
  } else r.h += dy;
  emit(
    "update:modelValue",
    clampCrop(
      props.locked ? lockedRect(r, corner) : r,
      props.width,
      props.height,
    ),
  );
}
</script>
<template>
  <div
    ref="host"
    class="absolute inset-0 touch-none"
    @pointermove="move"
    @pointerup="end"
    @pointercancel="end"
    @lostpointercapture="end"
  >
    <div
      v-for="(dim, index) in dims"
      :key="index"
      data-test="crop-dim"
      class="pointer-events-none absolute bg-black/55"
      :style="{
        top: dim.top + '%',
        left: dim.left + '%',
        width: dim.width + '%',
        height: dim.height + '%',
      }"
    />
    <div
      data-test="crop-box"
      class="absolute border-2 border-accent cursor-move"
      :style="{
        left: shown.x + '%',
        top: shown.y + '%',
        width: shown.w + '%',
        height: shown.h + '%',
      }"
      @pointerdown="start($event, null)"
    >
      <button
        v-for="corner in corners"
        :key="corner"
        type="button"
        class="absolute size-6 rounded border-2 border-white bg-accent"
        :class="[
          corner.startsWith('n') ? '-top-3' : '-bottom-3',
          corner.endsWith('w') ? '-left-3' : '-right-3',
        ]"
        :aria-label="`${t('clipEditor.crop')} ${corner}`"
        @pointerdown="start($event, corner)"
        @keydown="nudge($event, corner)"
      />
    </div>
  </div>
</template>
