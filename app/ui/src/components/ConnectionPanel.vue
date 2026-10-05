<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from "vue";
import type { State } from "@/api/types";
import { ui, messageOf } from "@/api/client";
import { copyText } from "@/lib/clipboard";
import { useStudio } from "@/composables/useStudio";
import { useConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { useI18n } from "@/i18n";
const props = defineProps<{ state: State }>();
const { t } = useI18n();
const token = ref<string | null>(null);
const tokenField = ref<HTMLInputElement | null>(null);
const pending = ref(false);
const error = ref<string | null>(null);
const manual = ref(false);
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
function hide() {
  clearTimeout(timer);
  token.value = null;
  manual.value = false;
}
function show(value: string) {
  if (disposed) return;
  token.value = value;
  clearTimeout(timer);
  timer = setTimeout(hide, 30_000);
}
async function fetchToken() {
  const value = token.value ?? (await ui.token()).token;
  show(value);
  return value;
}
async function reveal() {
  if (token.value) {
    hide();
    return;
  }
  await action(async () => {
    await fetchToken();
  });
}
async function action(work: () => Promise<void>) {
  if (pending.value) return;
  pending.value = true;
  error.value = null;
  manual.value = false;
  try {
    await work();
  } catch (cause) {
    if (!disposed) error.value = messageOf(cause);
  } finally {
    pending.value = false;
  }
}
async function copy(kind: "token" | "host") {
  await action(async () => {
    const text = await fetchToken();
    if (!text || disposed) return;
    if (await copyText(text)) useToast().push(t("system.copied"), "success");
    else {
      manual.value = true;
      await nextTick();
      const field = tokenField.value;
      field?.focus();
      field?.select();
    }
  });
}
async function rotate() {
  await action(async () => {
    if (
      !(await useConfirm().confirm({
        title: t("system.rotateTitle"),
        message: t("system.rotateBody"),
        confirmLabel: t("system.rotate"),
        danger: true,
      })) ||
      disposed
    )
      return;
    hide();
    await ui.rotateToken();
    await useStudio().refresh();
    useToast().push(t("system.rotated"), "success");
  });
}
onBeforeUnmount(() => {
  disposed = true;
  hide();
});
</script>
<template>
  <section class="panel min-w-0 space-y-4" aria-labelledby="connection-heading" :aria-busy="pending">
    <h3 id="connection-heading" class="font-semibold">{{ t("system.connection") }}</h3>
    <div class="flex flex-wrap items-center justify-between gap-2">
      <span class="text-sm text-muted">{{ t("system.discovery") }}</span>
      <span
        class="rounded-full border px-3 py-1 text-xs font-medium"
        :class="state.discovery.status === 'ok' ? 'border-ok/40 text-ok' : 'border-warn/40 text-warn'"
        >{{ t(`system.discovery.${state.discovery.status}`) }}</span
      >
    </div>
    <p v-if="state.discovery.message" class="text-sm break-words text-muted">{{ state.discovery.message }}</p>
    <div class="rounded-lg bg-ground p-3 text-sm">
      <h4 class="mb-1 font-medium">{{ t("system.manual") }}</h4>
      <p class="break-words">{{ t("system.connectionInfo") }}</p>
    </div>
    <div>
      <label for="system-token" class="mb-1 block text-sm">{{ t("system.token") }}</label>
      <input
        id="system-token"
        ref="tokenField"
        data-test="token"
        readonly
        class="field font-mono"
        autocomplete="off"
        spellcheck="false"
        :value="token ?? state.api_token_masked"
      />
      <p class="mt-1 text-xs text-muted">{{ t("system.tokenHint") }}</p>
      <div class="mt-2 flex flex-wrap gap-2">
        <button data-test="reveal-token" class="btn min-h-11!" :disabled="pending" @click="reveal">
          {{ token ? t("system.hide") : t("system.reveal") }}
        </button>
        <button data-test="copy-token" class="btn min-h-11!" :disabled="pending" @click="copy('token')">
          {{ t("system.copy") }}
        </button>
        <button
          data-test="rotate-token"
          class="btn-ghost min-h-11! text-danger!"
          :disabled="pending"
          @click="rotate"
        >
          {{ t("system.rotate") }}
        </button>
      </div>
    </div>
    <p v-if="pending" role="status" class="text-sm text-muted">{{ t("common.loading") }}</p>
    <p v-if="manual" role="status" class="text-sm text-warn">{{ t("system.copyManual") }}</p>
    <p v-if="error" role="alert" class="text-sm break-words text-danger">{{ error }}</p>
  </section>
</template>
