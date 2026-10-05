<script setup lang="ts">
import { ref } from "vue";
import { mdiAlertCircleOutline, mdiCheckCircleOutline, mdiFileVideoOutline, mdiTrashCanOutline, mdiUpload } from "@mdi/js";
import { ApiError, messageOf, ui } from "@/api/client";
import type { Asset } from "@/api/types";
import { useConfirm } from "@/composables/useConfirm";
import { useStudio } from "@/composables/useStudio";
import { useToast } from "@/composables/useToast";
import { UPLOAD_EXTENSIONS } from "@/composables/useUpload";
import { useI18n } from "@/i18n";
import { formatBytes } from "@/lib/format";
import EmptyState from "./EmptyState.vue";
import Icon from "./Icon.vue";
const { t, tp } = useI18n();
const { assets, refresh } = useStudio();
const pending = ref<string | null>(null);
const error = ref<string | null>(null);
const picker = ref<HTMLInputElement | null>(null);
const missingPickers = new Map<string, HTMLInputElement>();
const accept = UPLOAD_EXTENSIONS.join(",");
const supported = (name: string) => UPLOAD_EXTENSIONS.some((ext) => name.toLowerCase().endsWith(ext));

/** `expected` is set when the file must replace a missing asset: the name is what profiles reference. */
async function upload(event: Event, expected?: string): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file || pending.value) return;
  error.value = null;
  if (!supported(file.name)) {
    error.value = t("upload.unsupported");
    return;
  }
  if (expected !== undefined && file.name !== expected) {
    error.value = t("assets.nameMismatch", { name: expected });
    return;
  }
  pending.value = expected ?? file.name;
  try {
    const { affected_clip_ids } = await ui.assets.upload(file);
    await Promise.allSettled([refresh()]);
    useToast().push(t("organize.saved"), "success");
    if (affected_clip_ids.length) useToast().push(tp("profile.rerendering", affected_clip_ids.length), "success");
  } catch (cause) {
    error.value = messageOf(cause);
  } finally {
    pending.value = null;
  }
}

async function remove(asset: Asset): Promise<void> {
  if (pending.value) return;
  const confirmed = await useConfirm().confirm({
    title: t("organize.delete.title", { name: asset.filename }),
    message: t("organize.delete.message"),
    danger: true,
    confirmLabel: t("common.delete"),
  });
  if (!confirmed || pending.value) return;
  pending.value = asset.filename;
  error.value = null;
  try {
    await ui.assets.remove(asset.filename);
    await Promise.allSettled([refresh()]);
    useToast().push(t("organize.deleted"), "success");
  } catch (cause) {
    error.value = cause instanceof ApiError && cause.status === 409 ? t("assets.inUse") : messageOf(cause);
  } finally {
    pending.value = null;
  }
}
</script>
<template>
  <header class="mb-4 flex flex-wrap items-center justify-between gap-2">
    <h3 class="font-semibold">{{ t("organize.assets") }}</h3>
    <button type="button" class="btn-primary" :disabled="pending !== null" @click="picker?.click()">
      <Icon :path="mdiUpload" :size="18" /> {{ t("assets.upload") }}
    </button>
    <input
      ref="picker"
      data-test="asset-input"
      class="sr-only"
      tabindex="-1"
      type="file"
      :accept="accept"
      :aria-label="t('assets.upload')"
      @change="upload($event)"
    />
  </header>
  <p v-if="error" data-test="assets-error" class="mb-3 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm break-words text-danger">
    {{ error }}
  </p>
  <EmptyState
    v-if="!assets.length"
    :icon="mdiFileVideoOutline"
    :title="t('assets.empty.title')"
    :description="t('assets.empty.body')"
    ><button type="button" class="btn-primary" :disabled="pending !== null" @click="picker?.click()">
      {{ t("assets.upload") }}
    </button></EmptyState
  >
  <ul v-else class="space-y-3">
    <li
      v-for="asset in assets"
      :key="asset.filename"
      :data-missing="asset.status === 'missing' ? 'true' : undefined"
      class="rounded-lg border bg-ground p-3"
      :class="asset.status === 'missing' ? 'border-danger/50 bg-danger/5' : 'border-line'"
    >
      <div class="flex min-w-0 items-start gap-2">
        <span class="grid size-11 shrink-0 place-items-center rounded-lg bg-raised"
          ><Icon :path="mdiFileVideoOutline" :size="24"
        /></span>
        <div class="min-w-0 flex-1">
          <h4 class="truncate font-medium" :title="asset.filename">{{ asset.filename }}</h4>
          <p class="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
            <span
              :data-status="asset.status"
              class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium whitespace-nowrap"
              :class="asset.status === 'ready' ? 'border-ok/30 bg-ok/10 text-ok' : 'border-danger/40 bg-danger/10 text-danger'"
              ><Icon :path="asset.status === 'ready' ? mdiCheckCircleOutline : mdiAlertCircleOutline" :size="14" />{{
                t(`assets.status.${asset.status}`)
              }}</span
            >
            <span v-if="asset.size !== null" class="tabular-nums">{{ formatBytes(asset.size) }}</span>
          </p>
        </div>
        <span v-if="pending === asset.filename" role="status" :aria-label="t('common.loading')" class="mt-3 size-4 animate-spin rounded-full border-2 border-muted border-t-transparent" />
        <button
          type="button"
          class="btn-ghost size-11 shrink-0 p-0! text-danger!"
          :disabled="pending !== null"
          :aria-label="t('organize.delete', { name: asset.filename })"
          @click="remove(asset)"
        >
          <Icon :path="mdiTrashCanOutline" />
        </button>
      </div>
      <template v-if="asset.status === 'missing'">
        <p class="mt-2 text-sm text-danger">{{ t("assets.missingHint") }}</p>
        <button
          type="button"
          data-test="upload-missing"
          class="btn-primary mt-2 w-full"
          :disabled="pending !== null"
          @click="missingPickers.get(asset.filename)?.click()"
        >
          {{ t("assets.uploadMissing", { name: asset.filename }) }}
        </button>
        <input
          :ref="(el) => { if (el) missingPickers.set(asset.filename, el as HTMLInputElement); else missingPickers.delete(asset.filename); }"
          data-test="missing-input"
          class="sr-only"
          tabindex="-1"
          type="file"
          :accept="accept"
          :aria-label="t('assets.uploadMissing', { name: asset.filename })"
          @change="upload($event, asset.filename)"
        />
      </template>
    </li>
  </ul>
</template>
