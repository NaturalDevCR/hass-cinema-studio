<script setup lang="ts">
import { ref } from "vue";
import { mdiUpload } from "@mdi/js";
import Icon from "./Icon.vue";
import { UPLOAD_EXTENSIONS } from "@/composables/useUpload";
import { useStudio } from "@/composables/useStudio";
import { useI18n } from "@/i18n";
defineProps<{ disabled?: boolean }>();
const emit = defineEmits<{ files: [files: File[]] }>();
const { t } = useI18n();
const { state } = useStudio();
const input = ref<HTMLInputElement | null>(null);
const depth = ref(0);
function chooseFiles(): void {
  input.value?.click();
}
defineExpose({ chooseFiles });
function selected(event: Event): void {
  const target = event.target as HTMLInputElement;
  if (target.files) emit("files", Array.from(target.files));
  target.value = "";
}
function drop(event: DragEvent): void {
  depth.value = 0;
  if (event.dataTransfer?.files.length) emit("files", Array.from(event.dataTransfer.files));
}
</script>
<template>
  <div
    class="rounded-panel border-2 border-dashed border-line bg-surface p-6 text-center transition-colors"
    :class="{ 'border-accent! bg-accent-soft!': depth > 0 }"
    @dragenter.prevent="depth++"
    @dragover.prevent
    @dragleave.prevent="depth = Math.max(0, depth - 1)"
    @drop.prevent="!disabled && drop($event)"
  >
    <Icon :path="mdiUpload" :size="36" class="mb-2 text-accent" />
    <p class="font-medium">{{ t("upload.drop") }}</p>
    <p class="mt-2 text-xs leading-relaxed text-muted">
      {{ t("upload.formats") }}
    </p>
    <p v-if="state?.settings" class="mt-1 text-sm text-muted">
      {{ t("upload.limit", { n: state.settings.max_upload_mb }) }}
    </p>
    <input
      ref="input"
      class="sr-only"
      tabindex="-1"
      type="file"
      :accept="UPLOAD_EXTENSIONS.join(',')"
      multiple
      :disabled="disabled"
      :aria-label="t('upload.choose')"
      @change="selected"
    />
    <button type="button" class="btn-primary mt-4" :disabled="disabled" @click="chooseFiles">
      {{ t("upload.choose") }}
    </button>
  </div>
</template>
