<script setup lang="ts">
// Renders one @mdi/js path. Decorative (aria-hidden) unless a `label` is given.
withDefaults(defineProps<{ path: string; size?: number | string; label?: string }>(), { size: 20 });
</script>

<template>
  <svg
    viewBox="0 0 24 24"
    :width="size"
    :height="size"
    fill="currentColor"
    focusable="false"
    class="inline-block shrink-0"
    :role="label ? 'img' : undefined"
    :aria-label="label || undefined"
    :aria-hidden="label ? undefined : 'true'"
  >
    <path :d="path" />
  </svg>
</template>
