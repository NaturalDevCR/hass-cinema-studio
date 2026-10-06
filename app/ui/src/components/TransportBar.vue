<script setup lang="ts">
import { mdiPause, mdiPlay, mdiRepeat, mdiSkipNext, mdiSkipPrevious } from "@mdi/js";
import Icon from "@/components/Icon.vue";
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
      :title="t('clipEditor.in')"
      :aria-label="t('clipEditor.in')"
      @click="emit('jump', 'in')"
    >
      <Icon :path="mdiSkipPrevious" />
    </button>
    <button
      class="btn-primary min-w-14"
      :disabled="disabled"
      :title="t('clipEditor.play')"
      :aria-label="t('clipEditor.play')"
      :aria-pressed="playing"
      @click="emit('play')"
    >
      <Icon :path="playing ? mdiPause : mdiPlay" :size="24" />
    </button>
    <button
      class="btn"
      :disabled="disabled"
      :title="t('clipEditor.out')"
      :aria-label="t('clipEditor.out')"
      @click="emit('jump', 'out')"
    >
      <Icon :path="mdiSkipNext" />
    </button>
    <button
      class="btn"
      :aria-pressed="loop"
      :disabled="disabled"
      :title="t('clipEditor.loop')"
      @click="emit('loop')"
    >
      <Icon :path="mdiRepeat" />
      <span class="hidden sm:inline">{{ t("clipEditor.loop") }}</span>
    </button>
    <span class="ml-auto font-mono text-sm tabular-nums text-muted"
      ><span class="text-ink">{{ formatTimecode(position) }}</span> /
      {{ formatTimecode(length) }}</span
    >
  </div>
</template>
