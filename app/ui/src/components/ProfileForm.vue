<script setup lang="ts">
import { ref, useId, watch } from "vue";
import { messageOf, ui } from "@/api/client";
import type { NormalizationProfile } from "@/api/types";
import { formatDb, formatLufs } from "@/lib/format";
import { useI18n } from "@/i18n";
import { useStudio } from "@/composables/useStudio";
import { useJobs } from "@/composables/useJobs";
import { useToast } from "@/composables/useToast";
const props = defineProps<{ profile?: NormalizationProfile }>();
const emit = defineEmits<{
  saved: [profile: NormalizationProfile];
  busy: [pending: boolean];
}>();
const { t, tp } = useI18n();
const id = useId();
const name = ref(props.profile?.name ?? "");
const values = ref({
  target_lufs: props.profile?.target_lufs ?? -16,
  true_peak: props.profile?.true_peak ?? -1.5,
  lra: props.profile?.lra ?? 11,
});
const controls = [
  { key: "target_lufs", label: "targetLufs", min: -30, max: -5, step: 0.5, format: formatLufs },
  {
    key: "true_peak", label: "truePeak", min: -9, max: 0, step: 0.1,
    format: (n: number) => formatDb(n).replace("dB", "dBTP"),
  },
  { key: "lra", label: "lra", min: 1, max: 20, step: 0.5, format: (n: number) => `${n.toFixed(1)} LU` },
] as const;
const pending = ref(false);
const error = ref<string | null>(null);
watch(pending, (value) => emit("busy", value), { flush: "sync" });
async function submit(): Promise<void> {
  if (pending.value) return;
  if (!name.value.trim()) {
    error.value = t("form.nameRequired");
    return;
  }
  if (
    controls.some(
      (c) =>
        typeof values.value[c.key] !== "number" ||
        !Number.isFinite(values.value[c.key]) ||
        values.value[c.key] < c.min ||
        values.value[c.key] > c.max,
    )
  ) {
    error.value = t("profile.invalid");
    return;
  }
  pending.value = true;
  error.value = null;
  try {
    const body = { name: name.value.trim(), ...values.value };
    // The server marks the affected clips pending and queues their renders on PATCH.
    const { profile, affected_clip_ids } = props.profile
      ? await ui.normProfiles.update(props.profile.id, body)
      : { profile: await ui.normProfiles.create(body), affected_clip_ids: [] as string[] };
    await Promise.all([useStudio().refresh(), useJobs().refresh()]);
    useToast().push(t("organize.saved"), "success");
    if (affected_clip_ids.length) {
      useToast().push(tp("profile.rerendering", affected_clip_ids.length), "success");
    }
    emit("saved", profile);
  } catch (cause) {
    error.value = messageOf(cause);
  } finally {
    pending.value = false;
  }
}
</script>
<template>
  <form class="space-y-5" novalidate :aria-busy="pending" @submit.prevent="submit">
    <fieldset :disabled="pending" class="min-w-0 space-y-5">
      <div>
        <label :for="`${id}-name`" class="mb-1.5 block text-sm font-medium">{{ t("form.name") }}</label
        ><input :id="`${id}-name`" v-model="name" data-test="name" class="field" required maxlength="120" />
      </div>
      <div v-for="control in controls" :key="control.key" class="rounded-lg border border-line bg-ground p-3">
        <label :for="`${id}-${control.key}-number`" class="block text-sm font-medium">{{
          t(`profile.${control.label}`)
        }}</label>
        <div class="mt-2 flex min-w-0 items-center gap-3">
          <input
            v-model.number="values[control.key]"
            type="range"
            class="min-h-11 min-w-0 flex-1 accent-accent"
            :min="control.min"
            :max="control.max"
            :step="control.step"
            :aria-label="t(`profile.${control.label}`)"
            :aria-valuetext="control.format(Number(values[control.key]))"
            :aria-describedby="`${id}-${control.key}-help`"
          />
          <input
            :id="`${id}-${control.key}-number`"
            v-model.number="values[control.key]"
            :data-test="control.key"
            type="number"
            class="field w-24! shrink-0 tabular-nums"
            :min="control.min"
            :max="control.max"
            :step="control.step"
            :aria-describedby="`${id}-${control.key}-help`"
          />
        </div>
        <p :id="`${id}-${control.key}-help`" class="mt-2 text-sm text-muted">
          {{ t(`profile.${control.label}.hint`) }}
        </p>
      </div>
    </fieldset>
    <p v-if="error" role="alert" class="text-sm break-words text-danger">
      {{ error }}
    </p>
    <button type="submit" class="btn-primary w-full" :disabled="pending">
      {{ pending ? t("common.loading") : t("common.save") }}
    </button>
  </form>
</template>
