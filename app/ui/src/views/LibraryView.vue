<script setup lang="ts">
import { mdiFilmstripBox } from "@mdi/js";
import EmptyState from "@/components/EmptyState.vue";
import { useI18n } from "@/i18n";

// Foundation placeholder: the clip library lands with its own task. The child route (the
// clip editor sheet) renders through the RouterView so Library stays mounted underneath it.
const { t } = useI18n();
</script>

<template>
  <section data-test="library" class="min-w-0 space-y-4" aria-labelledby="library-heading">
    <h2 id="library-heading" class="text-xl font-semibold">{{ t("library.heading") }}</h2>
    <EmptyState :icon="mdiFilmstripBox" :title="t('library.empty.title')" :description="t('library.empty.body')" />
  </section>
  <RouterView />
</template>
