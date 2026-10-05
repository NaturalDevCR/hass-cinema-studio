<script setup lang="ts">
import { mdiUpload } from "@mdi/js";
import EmptyState from "@/components/EmptyState.vue";
import { useI18n } from "@/i18n";

// Foundation placeholder: the upload flow lands with its own task.
const { t } = useI18n();
</script>

<template>
  <section class="min-w-0 space-y-4" aria-labelledby="upload-heading">
    <h2 id="upload-heading" class="text-xl font-semibold">{{ t("upload.heading") }}</h2>
    <EmptyState :icon="mdiUpload" :title="t('upload.empty.title')" :description="t('upload.empty.body')" />
  </section>
</template>
