<script setup lang="ts">
import Icon from "@/components/Icon.vue";
import type { Season } from "@/api/types";
import { resolveIcon } from "@/lib/icons";

// The season color tints the border, background and icon; the label stays in the
// regular ink color so it keeps its contrast whatever color the user picked.
defineProps<{ season: Pick<Season, "name" | "color" | "icon">; compact?: boolean }>();
</script>

<template>
  <span
    class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap text-ink"
    :style="{
      '--season': season.color,
      borderColor: 'color-mix(in srgb, var(--season) 55%, transparent)',
      backgroundColor: 'color-mix(in srgb, var(--season) 16%, transparent)',
    }"
    :title="compact ? season.name : undefined"
  >
    <span class="inline-flex" :style="{ color: season.color }">
      <Icon :path="resolveIcon(season.icon)" :size="14" />
    </span>
    <span :class="{ 'sr-only': compact }">{{ season.name }}</span>
  </span>
</template>
