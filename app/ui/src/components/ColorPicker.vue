<script setup lang="ts">
import { ref, watch, useId } from "vue";
import { useI18n } from "@/i18n";
const props = defineProps<{ modelValue: string }>();
const emit = defineEmits<{
  "update:modelValue": [value: string];
  valid: [value: boolean];
}>();
const { t } = useI18n();
const id = useId();
const draft = ref(props.modelValue);
const valid = ref(/^#[0-9a-f]{6}$/i.test(draft.value));
const colors = [
  "#8b5cf6",
  "#6366f1",
  "#3b82f6",
  "#06b6d4",
  "#14b8a6",
  "#34d399",
  "#84cc16",
  "#fbbf24",
  "#f97316",
  "#f87171",
  "#ec4899",
  "#9aa1b2",
];
watch(
  () => props.modelValue,
  (value) => {
    draft.value = value;
    check();
  },
  { immediate: true },
);
function check(): void {
  valid.value = /^#[0-9a-f]{6}$/i.test(draft.value);
  emit("valid", valid.value);
}
function input(): void {
  check();
  if (valid.value) emit("update:modelValue", draft.value.toLowerCase());
}
function choose(color: string): void {
  draft.value = color;
  input();
}
</script>
<template>
  <fieldset class="min-w-0 space-y-2">
    <legend class="mb-2 text-sm font-medium">{{ t("form.color") }}</legend>
    <div class="grid grid-cols-6 gap-2">
      <button
        v-for="color in colors"
        :key="color"
        data-test="swatch"
        type="button"
        class="grid min-h-11 min-w-0 place-items-center rounded-lg border border-line"
        :class="{
          'outline-2 outline-accent outline-offset-2': modelValue === color,
        }"
        :aria-label="t('form.swatch', { color })"
        :aria-pressed="modelValue === color"
        @click="choose(color)"
      >
        <span class="size-6 rounded-full" :style="{ backgroundColor: color }" aria-hidden="true" />
      </button>
    </div>
    <label :for="id" class="block text-sm text-muted">{{ t("form.colorHex") }}</label>
    <input
      :id="id"
      v-model="draft"
      data-test="hex"
      class="field font-mono"
      type="text"
      spellcheck="false"
      :aria-invalid="!valid"
      :aria-describedby="!valid ? `${id}-error` : undefined"
      @input="input"
    />
    <p v-if="!valid" :id="`${id}-error`" role="alert" class="text-sm text-danger">
      {{ t("form.colorInvalid") }}
    </p>
  </fieldset>
</template>
