<script setup lang="ts">
import { formatTimecode } from "@/lib/format";
import { useI18n } from "@/i18n";
defineProps<{
  playing: boolean;
  loop: boolean;
  position: number;
  length: number;
  disabled?: boolean;
}>();
const emit = defineEmits<{ play: []; loop: []; jump: ["in" | "out"] }>();
const { t } = useI18n();
</script>
<template>
  <div
    class="flex flex-wrap items-center gap-2"
    role="toolbar"
    :aria-label="t('clipEditor.play')"
  >
    <button
      class="btn"
      :disabled="disabled"
      :aria-label="t('clipEditor.play')"
      :aria-pressed="playing"
      @click="emit('play')"
    >
      {{ playing ? "Ⅱ" : "▶" }}
    </button>
    <button class="btn" :disabled="disabled" @click="emit('jump', 'in')">
      {{ t("clipEditor.in") }}</button
    ><button class="btn" :disabled="disabled" @click="emit('jump', 'out')">
      {{ t("clipEditor.out") }}
    </button>
    <button
      class="btn"
      :aria-pressed="loop"
      :disabled="disabled"
      @click="emit('loop')"
    >
      {{ t("clipEditor.loop") }}
    </button>
    <span class="font-mono text-xs"
      >{{ formatTimecode(position) }} / {{ formatTimecode(length) }}</span
    >
  </div>
</template>
