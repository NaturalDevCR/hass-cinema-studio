<script setup lang="ts">
import { computed, ref } from "vue";
import Icon from "./Icon.vue";
import { ICON_NAMES, resolveIcon } from "@/lib/icons";
import { useI18n } from "@/i18n";
defineProps<{ modelValue: string }>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
const { t } = useI18n();
const search = ref("");
const names = computed(() =>
  ICON_NAMES.filter((name) => name.includes(search.value.trim().toLowerCase().replaceAll(" ", "-"))),
);
</script>
<template>
  <fieldset class="min-w-0 space-y-2">
    <legend class="mb-2 text-sm font-medium">{{ t("form.icon") }}</legend>
    <input
      v-model="search"
      class="field"
      type="search"
      :aria-label="t('form.iconSearch')"
      :placeholder="t('form.iconSearch')"
    />
    <div class="grid max-h-56 grid-cols-6 gap-2 overflow-y-auto p-1 sm:grid-cols-8">
      <button
        v-for="name in names"
        :key="name"
        type="button"
        class="grid min-h-11 min-w-0 place-items-center rounded-lg border border-line hover:bg-hover"
        :class="{
          'bg-accent-soft border-accent! text-accent': modelValue === name,
        }"
        :aria-label="t('form.iconChoose', { name: name.slice(4) })"
        :title="name.slice(4)"
        :aria-pressed="modelValue === name"
        @click="emit('update:modelValue', name)"
      >
        <Icon :path="resolveIcon(name)" :size="24" />
      </button>
    </div>
    <p v-if="!names.length" role="status" class="text-sm text-muted">
      {{ t("form.iconEmpty") }}
    </p>
  </fieldset>
</template>
