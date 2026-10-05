<script lang="ts">
// `useConfirm` is also reachable from here so either import path works.
export { useConfirm } from "@/composables/useConfirm";
</script>

<script setup lang="ts">
import { computed, ref, useId, watch } from "vue";
import { useConfirm, type ConfirmRequest } from "@/composables/useConfirm";
import { useModal } from "@/composables/useModal";
import { useI18n } from "@/i18n";

const { t } = useI18n();
const { request, answer } = useConfirm();

const open = computed(() => request.value !== null);
// Keep the last question around so its text does not flip to the defaults while the dialog fades out.
const shown = ref<ConfirmRequest | null>(null);
watch(request, (next) => {
  if (next) shown.value = next;
});

const title = computed(() => shown.value?.title ?? t("confirm.title"));
const message = computed(() => shown.value?.message ?? t("confirm.message"));
const confirmLabel = computed(() => shown.value?.confirmLabel ?? t("confirm.confirm"));
const cancelLabel = computed(() => shown.value?.cancelLabel ?? t("confirm.cancel"));
const danger = computed(() => shown.value?.danger === true);

const panel = ref<HTMLElement | null>(null);
const titleId = useId();
const bodyId = useId();

useModal(open, panel, {
  onEscape: () => answer(false),
  // Destructive questions start on Cancel so a stray Enter cannot delete anything.
  initialFocus: () =>
    panel.value?.querySelector<HTMLElement>(danger.value ? '[data-test="cancel"]' : '[data-test="confirm"]'),
});
</script>

<template>
  <Teleport to="body">
    <Transition name="dialog">
      <div v-if="open" class="dialog-root fixed inset-0 z-[60] grid place-items-center p-4">
        <div data-test="backdrop" class="absolute inset-0 bg-black/70" aria-hidden="true" @click="answer(false)" />
        <div
          ref="panel"
          role="alertdialog"
          aria-modal="true"
          tabindex="-1"
          :aria-labelledby="titleId"
          :aria-describedby="bodyId"
          class="dialog-panel relative w-full max-w-sm rounded-panel border border-line bg-raised p-5 shadow-2xl outline-none"
        >
          <h2 :id="titleId" class="text-lg font-semibold">{{ title }}</h2>
          <p :id="bodyId" class="mt-2 text-sm text-muted">{{ message }}</p>
          <div class="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button data-test="cancel" type="button" class="btn" @click="answer(false)">{{ cancelLabel }}</button>
            <button
              data-test="confirm"
              type="button"
              :class="danger ? 'btn-danger' : 'btn-primary'"
              @click="answer(true)"
            >
              {{ confirmLabel }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
