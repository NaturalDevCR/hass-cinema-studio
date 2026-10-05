<script setup lang="ts">
import { useI18n, type Locale } from "@/i18n";

const { t, locale, setLocale } = useI18n();
const options: Locale[] = ["es", "en"];
</script>

<template>
  <div role="group" :aria-label="t('lang.label')" class="inline-flex overflow-hidden rounded-lg border border-line bg-ground">
    <button
      v-for="code in options"
      :key="code"
      type="button"
      :lang="code"
      :aria-pressed="locale === code"
      class="min-h-11 min-w-11 px-2 text-xs font-semibold uppercase transition-colors focus-visible:-outline-offset-2"
      :class="locale === code ? 'bg-accent-soft text-ink' : 'text-muted hover:text-ink'"
      @click="setLocale(code)"
    >
      <span aria-hidden="true">{{ code }}</span>
      <span class="sr-only">{{ t(`lang.${code}`) }}</span>
    </button>
  </div>
</template>
