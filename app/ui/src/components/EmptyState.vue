<script setup lang="ts">
import Icon from "@/components/Icon.vue";

// Explains what is missing and offers the next step through the default slot.
defineProps<{ title: string; description?: string; icon?: string }>();
</script>

<template>
  <div
    class="flex flex-col items-center rounded-panel border border-dashed border-line px-6 py-10 text-center md:py-14"
  >
    <span v-if="icon" class="mb-4 grid size-14 place-items-center rounded-full bg-accent-soft text-accent">
      <Icon :path="icon" :size="28" />
    </span>
    <h3 class="text-lg font-semibold">{{ title }}</h3>
    <p v-if="description" class="mt-1 max-w-md text-sm text-balance text-muted">{{ description }}</p>
    <div v-if="$slots.default" class="mt-5 flex flex-wrap justify-center gap-2">
      <slot />
    </div>
  </div>
</template>
