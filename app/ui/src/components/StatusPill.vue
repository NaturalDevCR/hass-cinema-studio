<script setup lang="ts">
import { computed } from "vue";
import { mdiAlertCircleOutline, mdiCheckCircleOutline, mdiLoading } from "@mdi/js";
import type { ClipStatus } from "@/api/types";
import Icon from "@/components/Icon.vue";
import { useI18n } from "@/i18n";

const props = defineProps<{ status: ClipStatus; label?: string }>();
const { t } = useI18n();

// Color is never the only signal: every state also has its own icon and label.
const looks: Record<ClipStatus, { icon: string; tone: string; spin: boolean }> = {
  ready: { icon: mdiCheckCircleOutline, tone: "border-ok/30 bg-ok/10 text-ok", spin: false },
  processing: { icon: mdiLoading, tone: "border-accent/40 bg-accent-soft text-amber-200", spin: true },
  rendering: { icon: mdiLoading, tone: "border-accent/40 bg-accent-soft text-amber-200", spin: true },
  failed: { icon: mdiAlertCircleOutline, tone: "border-danger/40 bg-danger/10 text-danger", spin: false },
};
const look = computed(() => looks[props.status]);
</script>

<template>
  <span
    :data-status="status"
    class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap"
    :class="look.tone"
  >
    <Icon :path="look.icon" :size="14" :class="{ 'animate-spin': look.spin }" />
    {{ label ?? t(`status.${status}`) }}
  </span>
</template>
