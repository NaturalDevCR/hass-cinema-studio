<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watchEffect } from "vue";
import { useRoute } from "vue-router";
import { mdiAlertCircleOutline } from "@mdi/js";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import Icon from "@/components/Icon.vue";
import JobTray from "@/components/JobTray.vue";
import LocaleSwitch from "@/components/LocaleSwitch.vue";
import NavBar from "@/components/NavBar.vue";
import ToastStack from "@/components/ToastStack.vue";
import { useJobs } from "@/composables/useJobs";
import { useStudio } from "@/composables/useStudio";
import { useI18n, type MessageKey } from "@/i18n";

const { t } = useI18n();
const route = useRoute();
const { error, loading, refresh } = useStudio();
const jobs = useJobs();

const main = ref<HTMLElement | null>(null);
// The clip editor is a child of Library, so the first matched record always owns the title.
const titleKey = computed<MessageKey>(() => route.matched[0]?.meta.titleKey ?? "app.name");

watchEffect(() => {
  document.title = `${t(titleKey.value)} · ${t("app.fullName")}`;
});

onMounted(() => {
  void refresh();
  jobs.start();
});
onBeforeUnmount(() => jobs.stop());
</script>

<template>
  <button
    type="button"
    class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[80] focus:rounded-lg focus:bg-accent-strong focus:px-4 focus:py-3 focus:text-sm focus:font-semibold focus:text-accent-ink"
    @click="main?.focus()"
  >
    {{ t("app.skipToContent") }}
  </button>

  <div class="min-h-dvh md:flex">
    <NavBar />

    <div class="flex min-w-0 flex-1 flex-col">
      <header
        class="sticky top-0 z-30 flex min-h-14 items-center gap-2 border-b border-line bg-ground/85 px-4 pt-[env(safe-area-inset-top)] backdrop-blur-md md:px-8"
      >
        <h1 class="min-w-0 flex-1 truncate text-lg font-semibold">{{ t(titleKey) }}</h1>
        <div class="md:hidden">
          <LocaleSwitch />
        </div>
        <JobTray />
      </header>

      <div
        v-if="error"
        role="alert"
        class="mx-4 mt-4 flex flex-wrap items-center gap-3 rounded-panel border border-danger/40 bg-danger/10 p-3 text-sm md:mx-8"
      >
        <Icon :path="mdiAlertCircleOutline" :size="22" class="text-danger" />
        <div class="min-w-0 flex-1">
          <p class="font-semibold text-danger">{{ t("error.title") }}</p>
          <p class="break-words">{{ error }}</p>
        </div>
        <button type="button" class="btn" :disabled="loading" @click="refresh()">{{ t("common.retry") }}</button>
      </div>

      <main
        id="main"
        ref="main"
        tabindex="-1"
        class="min-w-0 flex-1 px-4 py-5 pb-[calc(var(--tabbar-h)+1.5rem)] outline-none md:px-8 md:py-6 md:pb-8"
      >
        <RouterView />
      </main>
    </div>
  </div>

  <ConfirmDialog />
  <ToastStack />
</template>
