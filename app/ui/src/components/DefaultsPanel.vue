<script setup lang="ts">
import { ref, watch } from "vue";
import type { Settings } from "@/api/types";
import { useSettingsSave } from "@/composables/useSettingsSave";
import { useI18n } from "@/i18n";
const props = defineProps<{ settings: Settings }>();
const { t } = useI18n();
const { pending, error, save } = useSettingsSave();
const GIB = 1024 ** 3;
const MAX_MARGIN_S = 10;
const lead = ref(props.settings.default_lead_in);
const tail = ref(props.settings.default_tail_out);
const uploadMb = ref(props.settings.max_upload_mb);
const durationS = ref(props.settings.max_duration_s);
const reserveGb = ref(props.settings.disk_reserve_bytes / GIB);
const validation = ref<string | null>(null);
// Show what the server last saved, so a refresh after another save never leaves stale fields.
watch(
  () => props.settings,
  (settings) => {
    lead.value = settings.default_lead_in;
    tail.value = settings.default_tail_out;
    uploadMb.value = settings.max_upload_mb;
    durationS.value = settings.max_duration_s;
    reserveGb.value = settings.disk_reserve_bytes / GIB;
  },
);
const inMargin = (value: number) => Number.isFinite(value) && value >= 0 && value <= MAX_MARGIN_S;
const positive = (value: number) => Number.isFinite(value) && value > 0;
async function submit() {
  validation.value = null;
  if (!inMargin(lead.value) || !inMargin(tail.value)) {
    validation.value = t("system.defaultsMarginInvalid");
    return;
  }
  if (!positive(uploadMb.value) || !positive(durationS.value) || !positive(reserveGb.value)) {
    validation.value = t("system.defaultsLimitInvalid");
    return;
  }
  await save({
    default_lead_in: lead.value,
    default_tail_out: tail.value,
    max_upload_mb: uploadMb.value,
    max_duration_s: durationS.value,
    disk_reserve_bytes: Math.round(reserveGb.value * GIB),
  });
}
</script>
<template>
  <section class="panel min-w-0 space-y-4" aria-labelledby="defaults-heading" :aria-busy="pending">
    <h3 id="defaults-heading" class="font-semibold">{{ t("system.defaults") }}</h3>
    <form class="grid gap-3 sm:grid-cols-2" novalidate @submit.prevent="submit">
      <label class="text-sm" for="defaults-lead"
        >{{ t("system.defaultLead") }}
        <input
          id="defaults-lead"
          v-model.number="lead"
          type="number"
          min="0"
          :max="MAX_MARGIN_S"
          step="0.1"
          inputmode="decimal"
          class="field mt-1"
        />
      </label>
      <label class="text-sm" for="defaults-tail"
        >{{ t("system.defaultTail") }}
        <input
          id="defaults-tail"
          v-model.number="tail"
          type="number"
          min="0"
          :max="MAX_MARGIN_S"
          step="0.1"
          inputmode="decimal"
          class="field mt-1"
        />
      </label>
      <label class="text-sm" for="defaults-upload"
        >{{ t("system.maxUpload") }}
        <input
          id="defaults-upload"
          v-model.number="uploadMb"
          type="number"
          min="1"
          step="1"
          inputmode="numeric"
          class="field mt-1"
        />
      </label>
      <label class="text-sm" for="defaults-duration"
        >{{ t("system.maxDuration") }}
        <input
          id="defaults-duration"
          v-model.number="durationS"
          type="number"
          min="1"
          step="1"
          inputmode="numeric"
          class="field mt-1"
        />
      </label>
      <label class="text-sm sm:col-span-2" for="defaults-reserve"
        >{{ t("system.diskReserve") }}
        <input
          id="defaults-reserve"
          v-model.number="reserveGb"
          type="number"
          min="0.1"
          step="0.1"
          inputmode="decimal"
          class="field mt-1"
        />
      </label>
      <button class="btn-primary min-h-11! sm:col-span-2" type="submit" :disabled="pending">
        {{ t("common.save") }}
      </button>
    </form>
    <p v-if="validation" role="alert" class="text-sm text-warn">{{ validation }}</p>
    <p v-if="error" role="alert" class="text-sm break-words text-danger">{{ error }}</p>
  </section>
</template>
