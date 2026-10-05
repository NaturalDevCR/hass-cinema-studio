<script setup lang="ts">
import { ref, onBeforeUnmount } from "vue";
import { mdiAlertCircleOutline, mdiFilmstripBox, mdiPlay, mdiStop, mdiCheckboxBlankCircleOutline, mdiCheckCircle } from "@mdi/js";
import type { Clip } from "@/api/types";
import { posterUrl, mediaUrl } from "@/api/client";
import Icon from "@/components/Icon.vue";
import StatusPill from "@/components/StatusPill.vue";
import { formatDuration, formatLufs } from "@/lib/format";
import { useI18n } from "@/i18n";
import { usePlayer } from "@/composables/usePlayer";
const props = defineProps<{ clip: Clip; selected?: boolean; selecting?: boolean; playing?: boolean }>();
const emit = defineEmits<{ open: [id: string]; play: [id: string]; select: [id: string] }>();
const { t } = useI18n(); const posterFailed = ref(false); let pressTimer: ReturnType<typeof setTimeout> | undefined; let swallowClick = false;
const player = usePlayer(); const previewHost = ref<HTMLElement | null>(null);
function onPointerDown(e: PointerEvent) { if (e.pointerType === "mouse" || props.selecting) return; pressTimer = setTimeout(() => { swallowClick = true; emit("select", props.clip.id); }, 450); }
function clearPress() { clearTimeout(pressTimer); }
function openClip() { if (swallowClick) { swallowClick = false; return; } emit("open", props.clip.id); }
onBeforeUnmount(clearPress);
</script>
<template><article class="group relative overflow-hidden rounded-panel border border-line bg-surface" :class="{ 'opacity-60': !clip.enabled, 'border-accent': selected }" @pointerdown="onPointerDown" @pointerup="clearPress" @pointercancel="clearPress" @pointerleave="clearPress"><div ref="previewHost" class="relative aspect-video bg-ground"><img v-if="!posterFailed" :src="posterUrl(clip.id, clip.render?.id)" alt="" loading="lazy" class="size-full object-cover" @error="posterFailed = true" /><div v-else class="grid size-full place-items-center text-muted"><Icon :path="mdiFilmstripBox" :size="42" /></div><button data-test="play" class="absolute bottom-2 right-2 z-10 grid size-10 place-items-center rounded-full bg-black/75 text-white" :aria-label="t('library.play', { title: clip.title })" :disabled="!clip.render" @click.stop="emit('play', clip.id); player.toggle(clip.id, mediaUrl(clip.id, 'render', clip.render?.id), previewHost ?? undefined)"><Icon :path="playing ? mdiStop : mdiPlay" :size="24" /></button><button data-test="select" role="checkbox" :aria-checked="selected" :aria-label="t('library.select', { title: clip.title })" class="absolute left-2 top-2 z-10 grid size-9 place-items-center rounded-full bg-black/75 text-white" @click.stop="emit('select', clip.id)"><Icon :path="selected ? mdiCheckCircle : mdiCheckboxBlankCircleOutline" /></button><span v-if="clip.render_pending" data-test="pending" class="absolute right-2 top-2 rounded bg-amber-600 px-2 py-1 text-xs">{{ t('library.pending') }}</span><span v-if="clip.needs_source" data-test="needs-source" class="absolute bottom-2 left-2 rounded bg-red-700 px-2 py-1 text-xs"><Icon :path="mdiAlertCircleOutline" :size="14" /> {{ t('library.needsSource') }}</span></div><button data-test="open" class="block w-full p-3 text-left" @click="openClip"><span class="block truncate font-medium">{{ clip.title }}</span><span class="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted tabular-nums"><span>{{ clip.render ? formatDuration(clip.render.duration) : '—' }}</span><span v-if="clip.render">{{ formatDuration(clip.render.content_duration) }} {{ t('library.content') }}</span><span>{{ formatLufs(clip.render?.integrated_lufs ?? null) }}</span></span><span class="mt-2 flex flex-wrap items-center gap-2"><StatusPill v-if="clip.status !== 'ready'" :status="clip.status" /><span v-if="!clip.enabled" class="rounded-full bg-hover px-2 py-0.5 text-xs">{{ t('library.disabled') }}</span></span></button></article></template>
