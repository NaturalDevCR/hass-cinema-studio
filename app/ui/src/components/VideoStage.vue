<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { Clip, MediaKind, Recipe } from "@/api/types";
import { mediaUrl } from "@/api/client";
import CropOverlay from "./CropOverlay.vue";
import { clampCrop, type Rect } from "@/lib/crop";
import { useI18n } from "@/i18n";
const props = defineProps<{
  clip: Clip;
  recipe: Recipe;
  source: MediaKind;
  previewVersion: string;
  loop: boolean;
  fadeIn: number;
  fadeOut: number;
}>();
const emit = defineEmits<{
  position: [number];
  playing: [boolean];
  crop: [Rect | null];
}>();
const { t } = useI18n();
const video = ref<HTMLVideoElement | null>(null),
  locked = ref(false),
  opacity = ref(0),
  error = ref(false);
let frame = 0;
const original = computed(() => props.source === "original");
const ratio = computed(() =>
  original.value && props.clip.original
    ? { w: props.clip.original.width, h: props.clip.original.height }
    : { w: 16, h: 9 },
);
const url = computed(() =>
  mediaUrl(
    props.clip.id,
    props.source,
    props.source === "preview"
      ? props.previewVersion
      : props.source === "render"
        ? props.clip.render?.id
        : props.clip.original?.sha256,
  ),
);
watch(locked, (value) => {
  // Locking only constrains later edits; with no crop there is nothing to snap,
  // so the recipe stays untouched until the user actually changes the crop.
  const r = props.recipe.crop;
  if (!value || !props.clip.original || !r) return;
  const original = props.clip.original;
  const w = Math.min(r.w, (r.h * 16) / 9);
  emit(
    "crop",
    clampCrop({ ...r, w, h: (w * 9) / 16 }, original.width, original.height),
  );
});
function bounds(): [number, number] {
  return original.value
    ? [
        props.recipe.trim_start,
        props.recipe.trim_end ?? props.clip.original?.duration ?? 0,
      ]
    : [0, video.value?.duration || 0];
}
function seek(time: number) {
  if (video.value) {
    video.value.currentTime = time;
    tick(false);
  }
}
function jump(edge: "in" | "out") {
  seek(bounds()[edge === "in" ? 0 : 1]);
}
async function toggle() {
  const v = video.value;
  if (!v) return;
  if (v.paused) {
    const [start, end] = bounds();
    if (v.currentTime < start || v.currentTime >= end) v.currentTime = start;
    try {
      await v.play();
    } catch {
      error.value = true;
    }
  } else v.pause();
}
/** Fade simulation applies only while the original is actually playing. */
function applyFade() {
  const v = video.value;
  if (!v) return;
  const [start, end] = bounds();
  const live = original.value && !v.paused && !v.seeking;
  const fade = live
    ? Math.max(
        0,
        Math.min(
          1,
          props.fadeIn > 0 ? (v.currentTime - start) / props.fadeIn : 1,
          props.fadeOut > 0 ? (end - v.currentTime) / props.fadeOut : 1,
        ),
      )
    : 1;
  opacity.value = 1 - fade;
  v.volume = fade;
}
function tick(schedule = true) {
  const v = video.value;
  if (!v) return;
  const [start, end] = bounds();
  if (!v.paused && end > start && v.currentTime >= end) {
    if (props.loop) v.currentTime = start;
    else v.pause();
  }
  applyFade();
  emit("position", v.currentTime);
  if (schedule && !v.paused) frame = requestAnimationFrame(() => tick());
}
function play() {
  cancelAnimationFrame(frame);
  emit("playing", true);
  tick();
}
function ended() {
  if (props.loop) {
    jump("in");
    void toggle();
  } else pause();
}
function pause() {
  cancelAnimationFrame(frame);
  applyFade();
  emit("playing", false);
}
watch(
  () => [
    props.fadeIn,
    props.fadeOut,
    props.recipe.trim_start,
    props.recipe.trim_end,
  ],
  applyFade,
);
watch(url, () => {
  cancelAnimationFrame(frame);
  error.value = false;
  opacity.value = 0;
  emit("position", 0);
  emit("playing", false);
});
onBeforeUnmount(() => cancelAnimationFrame(frame));
defineExpose({ toggle, seek, jump });
</script>
<template>
  <div class="space-y-3">
    <div
      data-test="stage-box"
      class="relative mx-auto max-h-[70vh] bg-black"
      :style="{
        aspectRatio: `${ratio.w} / ${ratio.h}`,
        width: `min(100%, calc(70vh * ${ratio.w / ratio.h}))`,
      }"
    >
      <video
        ref="video"
        :src="url"
        class="h-full w-full object-contain"
        playsinline
        preload="metadata"
        @play="play"
        @pause="pause"
        @ended="ended"
        @timeupdate="tick(false)"
        @seeking="tick(false)"
        @seeked="tick(false)"
        @error="error = true"
      />
      <div
        data-test="fade-overlay"
        class="absolute inset-0 bg-black pointer-events-none"
        :style="{ opacity }"
      />
      <CropOverlay
        v-if="original && clip.original"
        :model-value="recipe.crop"
        :width="clip.original.width"
        :height="clip.original.height"
        :locked="locked"
        @update:model-value="emit('crop', $event)"
      />
    </div>
    <div v-if="original && clip.original" class="flex items-center gap-3">
      <label
        ><input v-model="locked" type="checkbox" />
        {{ t("clipEditor.aspect") }}</label
      ><button class="btn" @click="emit('crop', null)">
        {{ t("clipEditor.resetCrop") }}
      </button>
    </div>
    <p v-if="error" role="alert" class="text-danger">
      {{ t("clipEditor.videoError") }}
    </p>
  </div>
</template>
