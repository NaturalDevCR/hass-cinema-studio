<script setup lang="ts">
import { mdiAlertCircleOutline, mdiCheckCircleOutline, mdiClose, mdiInformationOutline } from "@mdi/js";
import Icon from "@/components/Icon.vue";
import { useToast, type ToastKind } from "@/composables/useToast";
import { useI18n } from "@/i18n";

const { t } = useI18n();
const { toasts, dismiss } = useToast();

const look: Record<ToastKind, { icon: string; tone: string }> = {
  info: { icon: mdiInformationOutline, tone: "text-amber-200" },
  success: { icon: mdiCheckCircleOutline, tone: "text-ok" },
  error: { icon: mdiAlertCircleOutline, tone: "text-danger" },
};
</script>

<template>
  <!-- Teleported outside #app so it is never marked inert, and above the Sheet layer so it stays
       readable. The container is one persistent polite live region (it exists before the first
       toast, which is what makes screen readers announce additions); items carry no role. While a
       modal is open its focus trap keeps keyboard focus inside the modal, which is acceptable
       because toasts dismiss themselves; with no modal open the dismiss buttons are in the tab order. -->
  <Teleport to="body">
    <div
      role="status"
      aria-live="polite"
      aria-relevant="additions text"
      data-test="toasts"
      class="pointer-events-none fixed inset-x-0 top-[calc(3.5rem+env(safe-area-inset-top,0px)+0.75rem)] z-[70] flex flex-col items-center gap-2 px-4 md:inset-x-auto md:right-4 md:top-auto md:bottom-4 md:items-end"
    >
      <TransitionGroup name="toast">
        <div
          v-for="toast in toasts"
          :key="toast.id"
          :data-kind="toast.kind"
          class="pointer-events-auto flex w-full max-w-md items-center gap-2 rounded-panel border border-line bg-raised py-1 pr-1 pl-3 shadow-xl"
        >
          <Icon :path="look[toast.kind].icon" :class="look[toast.kind].tone" />
          <p class="min-w-0 flex-1 py-2 text-sm break-words">{{ toast.message }}</p>
          <button type="button" class="btn-ghost size-11 shrink-0 p-0!" :aria-label="t('toast.dismiss')" @click="dismiss(toast.id)">
            <Icon :path="mdiClose" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>
