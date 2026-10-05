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
  if (!value || !props.clip.original) return;
  const original = props.clip.original;
  const r = props.recipe.crop ?? {
    x: 0,
    y: 0,
    w: original.width,
    h: original.height,
  };
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
function tick(schedule = true) {
  const v = video.value;
  if (!v) return;
  const [start, end] = bounds();
  if (!v.paused && end > start && v.currentTime >= end) {
    if (props.loop) v.currentTime = start;
    else v.pause();
  }
  const fade = original.value
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
  emit("playing", false);
}
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
      class="relative mx-auto bg-black"
      :style="{
        aspectRatio:
          original && clip.original
            ? `${clip.original.width}/${clip.original.height}`
            : '16/9',
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
        @error="error = true"
      />
      <div
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
