<script setup lang="ts">
import { computed, ref, useId, watch } from "vue";
import { ui } from "@/api/client";
import type { ProcessingProfile, ProcessingProfileSettings } from "@/api/types";
import { useI18n } from "@/i18n";
import { useFormMutation } from "@/composables/useFormMutation";
import { useStudio } from "@/composables/useStudio";
import { useToast } from "@/composables/useToast";
import {
  DEFAULT_PROCESSING_SETTINGS,
  RESOLUTION_PRESETS,
  applyResolution,
  clone,
  resolutionOf,
  setTransitionSeconds,
  transitionSeconds,
  type ResolutionPreset,
} from "@/lib/processing";
const props = defineProps<{ profile?: ProcessingProfile }>();
const emit = defineEmits<{
  saved: [profile: ProcessingProfile];
  busy: [pending: boolean];
}>();
const { t, tp } = useI18n();
const id = useId();
const { assets } = useStudio();
// After a successful create the form edits that profile, so a retry cannot create a duplicate.
const current = ref(props.profile);
const name = ref(props.profile?.name ?? "");
const settings = ref<ProcessingProfileSettings>(clone(props.profile?.settings ?? DEFAULT_PROCESSING_SETTINGS));
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
const json = ref(pretty(settings.value));
const jsonError = ref<string | null>(null);
// Last two-pass targets, so switching loudness off and on again does not lose them.
type TwoPass = Extract<ProcessingProfileSettings["loudness"], { mode: "two_pass" }>;
let lastTwoPass: TwoPass | null = settings.value.loudness.mode === "two_pass" ? { ...settings.value.loudness } : null;

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
// Advanced JSON may hold a partial document (the server fills in defaults); the fields need every section.
const complete = computed(() => {
  const s = settings.value as Partial<ProcessingProfileSettings>;
  return (
    isObject(s.video) && isObject(s.video.quality) && isObject(s.video.scaling) && isObject(s.audio) &&
    isObject(s.loudness) && Array.isArray(s.transitions)
  );
});
function onJson(event: Event): void {
  json.value = (event.target as HTMLTextAreaElement).value;
  let parsed: unknown;
  try {
    parsed = JSON.parse(json.value);
  } catch {
    jsonError.value = t("processing.jsonInvalid");
    return;
  }
  if (!isObject(parsed)) {
    jsonError.value = t("processing.jsonObject");
    return;
  }
  jsonError.value = null;
  settings.value = parsed as unknown as ProcessingProfileSettings;
  if (settings.value.loudness?.mode === "two_pass") lastTwoPass = { ...settings.value.loudness };
}
/** A structured edit regenerates the Advanced JSON from the settings. */
function edited(): void {
  json.value = pretty(settings.value);
  jsonError.value = null;
}

const numberOf = (event: Event): number | null => {
  const raw = (event.target as HTMLInputElement).value;
  return raw.trim() === "" || !Number.isFinite(Number(raw)) ? null : Number(raw);
};
// Required numbers ignore an empty or invalid entry (the server still validates ranges on save).
function setNumber(event: Event, apply: (value: number) => void): void {
  const value = numberOf(event);
  if (value === null) return;
  apply(value);
  edited();
}

const resolution = computed(() => resolutionOf(settings.value.video));
function onResolution(event: Event): void {
  const choice = (event.target as HTMLSelectElement).value;
  if (choice in RESOLUTION_PRESETS) applyResolution(settings.value, choice as ResolutionPreset);
  edited();
}
const quality = computed(() => settings.value.video.quality);
const sampleRates = computed(() => {
  const rate = settings.value.audio.sample_rate;
  return [...new Set([44100, 48000, 96000, rate])].sort((a, b) => a - b);
});
const twoPass = computed(() => settings.value.loudness.mode === "two_pass");
function onTwoPass(event: Event): void {
  const on = (event.target as HTMLInputElement).checked;
  const final = settings.value.loudness.final_mix_normalization;
  if (settings.value.loudness.mode === "two_pass") lastTwoPass = { ...settings.value.loudness };
  settings.value.loudness = on
    ? { ...(lastTwoPass ?? (DEFAULT_PROCESSING_SETTINGS.loudness as TwoPass)), final_mix_normalization: final }
    : { mode: "disabled", final_mix_normalization: final };
  edited();
}
function setLoudness(event: Event, key: "integrated_lufs" | "true_peak_dbtp" | "lra_lu"): void {
  setNumber(event, (value) => {
    if (settings.value.loudness.mode === "two_pass") settings.value.loudness[key] = value;
  });
}

type Edge = "intro" | "outro";
const reference = (edge: Edge) => settings.value[`${edge}_reference`];
function assetOptions(edge: Edge) {
  const chosen = reference(edge);
  const options = assets.value.map((a) => ({
    value: a.filename,
    label: a.status === "missing" ? t("processing.missingAsset", { name: a.filename }) : a.filename,
  }));
  if (chosen && !assets.value.some((a) => a.filename === chosen)) {
    options.push({ value: chosen, label: t("processing.missingAsset", { name: chosen }) });
  }
  return options;
}
function onAsset(event: Event, edge: Edge): void {
  const chosen = (event.target as HTMLSelectElement).value || null;
  settings.value[`${edge}_reference`] = chosen;
  // The transition follows the asset: dropped with it, defaulting to one second when first chosen.
  if (!chosen) setTransitionSeconds(settings.value, edge, null);
  else if (transitionSeconds(settings.value, edge) === null) setTransitionSeconds(settings.value, edge, 1);
  edited();
}
function onTransition(event: Event, edge: Edge): void {
  const value = numberOf(event);
  setTransitionSeconds(settings.value, edge, value !== null && value > 0 ? value : null);
  edited();
}

const { pending, error, save } = useFormMutation();
watch(pending, (value) => emit("busy", value), { flush: "sync" });
async function submit(): Promise<void> {
  if (pending.value) return;
  if (!name.value.trim()) {
    error.value = t("form.nameRequired");
    return;
  }
  if (jsonError.value) {
    error.value = jsonError.value;
    return;
  }
  const body = { name: name.value.trim(), settings: settings.value };
  await save(
    async () => {
      if (!current.value) {
        current.value = await ui.procProfiles.create(body);
        return { profile: current.value, affected_clip_ids: [] as string[] };
      }
      const result = await ui.procProfiles.update(current.value.id, body);
      current.value = result.profile;
      return result;
    },
    ({ profile, affected_clip_ids }) => {
      if (affected_clip_ids.length) useToast().push(tp("profile.rerendering", affected_clip_ids.length), "success");
      emit("saved", profile);
    },
  );
}
</script>
<template>
  <form class="space-y-5" novalidate :aria-busy="pending" @submit.prevent="submit">
    <fieldset :disabled="pending" class="min-w-0 space-y-5">
      <div>
        <label :for="`${id}-name`" class="mb-1.5 block text-sm font-medium">{{ t("form.name") }}</label
        ><input :id="`${id}-name`" v-model="name" data-test="name" class="field" required maxlength="120" />
      </div>
      <p v-if="!complete" data-test="partial-hint" class="text-sm text-muted">{{ t("processing.partial") }}</p>
      <template v-else>
        <section class="min-w-0 space-y-3 rounded-lg border border-line bg-ground p-3">
          <h4 class="text-sm font-semibold">{{ t("processing.video") }}</h4>
          <div>
            <label :for="`${id}-resolution`" class="mb-1.5 block text-sm font-medium">{{ t("processing.resolution") }}</label>
            <select :id="`${id}-resolution`" :value="resolution" data-test="resolution" class="field" @change="onResolution">
              <option value="4k">{{ t("processing.resolution.4k") }}</option>
              <option value="1080p">{{ t("processing.resolution.1080p") }}</option>
              <option value="720p">{{ t("processing.resolution.720p") }}</option>
              <option v-if="resolution === 'custom'" value="custom">
                {{ t("processing.resolution.custom", { w: settings.video.width, h: settings.video.height }) }}
              </option>
            </select>
          </div>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label class="min-w-0 text-sm font-medium"
              >{{ t("processing.fps")
              }}<input
                :value="settings.video.fps"
                data-test="fps"
                type="number"
                min="1"
                max="240"
                step="1"
                class="field mt-1"
                @input="setNumber($event, (v) => (settings.video.fps = v))"
            /></label>
            <label v-if="quality.mode === 'crf'" class="min-w-0 text-sm font-medium"
              >{{ t("processing.crf")
              }}<input
                :value="quality.crf"
                data-test="crf"
                type="number"
                min="0"
                max="51"
                step="1"
                class="field mt-1"
                @input="setNumber($event, (v) => { if (quality.mode === 'crf') quality.crf = v; })"
            /></label>
            <label v-else class="min-w-0 text-sm font-medium"
              >{{ t("processing.bitrate")
              }}<input
                :value="quality.bitrate_kbps"
                data-test="bitrate"
                type="number"
                min="1"
                step="100"
                class="field mt-1"
                @input="setNumber($event, (v) => { if (quality.mode === 'bitrate') quality.bitrate_kbps = v; })"
            /></label>
            <label class="min-w-0 text-sm font-medium"
              >{{ t("processing.maxrate")
              }}<input
                :value="settings.video.maxrate_kbps ?? ''"
                data-test="maxrate"
                type="number"
                min="1"
                step="100"
                class="field mt-1"
                @input="settings.video.maxrate_kbps = numberOf($event); edited()"
            /></label>
          </div>
        </section>
        <section class="min-w-0 space-y-3 rounded-lg border border-line bg-ground p-3">
          <h4 class="text-sm font-semibold">{{ t("processing.audio") }}</h4>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label class="min-w-0 text-sm font-medium"
              >{{ t("processing.audioBitrate")
              }}<input
                :value="settings.audio.bitrate_kbps"
                data-test="audio-bitrate"
                type="number"
                min="1"
                step="16"
                class="field mt-1"
                @input="setNumber($event, (v) => (settings.audio.bitrate_kbps = v))"
            /></label>
            <label class="min-w-0 text-sm font-medium"
              >{{ t("processing.sampleRate")
              }}<select
                :value="settings.audio.sample_rate"
                data-test="audio-rate"
                class="field mt-1"
                @change="setNumber($event, (v) => (settings.audio.sample_rate = v))"
              >
                <option v-for="rate in sampleRates" :key="rate" :value="rate">{{ rate }}</option>
              </select></label
            >
          </div>
        </section>
        <section class="min-w-0 space-y-3 rounded-lg border border-line bg-ground p-3">
          <h4 class="text-sm font-semibold">{{ t("processing.loudness") }}</h4>
          <label class="flex min-h-11 items-center gap-3 text-sm font-medium">
            <input :checked="twoPass" data-test="two-pass" type="checkbox" class="size-5 accent-accent" @change="onTwoPass" />
            {{ t("processing.twoPass") }}
          </label>
          <div v-if="settings.loudness.mode === 'two_pass'" class="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label class="min-w-0 text-sm font-medium"
              >{{ t("processing.lufs")
              }}<input
                :value="settings.loudness.integrated_lufs"
                data-test="lufs"
                type="number"
                min="-70"
                max="-5"
                step="0.5"
                class="field mt-1"
                @input="setLoudness($event, 'integrated_lufs')"
            /></label>
            <label class="min-w-0 text-sm font-medium"
              >{{ t("processing.truePeak")
              }}<input
                :value="settings.loudness.true_peak_dbtp"
                data-test="true-peak"
                type="number"
                min="-20"
                max="0"
                step="0.1"
                class="field mt-1"
                @input="setLoudness($event, 'true_peak_dbtp')"
            /></label>
            <label class="min-w-0 text-sm font-medium"
              >{{ t("processing.lra")
              }}<input
                :value="settings.loudness.lra_lu"
                data-test="lra"
                type="number"
                min="1"
                max="50"
                step="0.5"
                class="field mt-1"
                @input="setLoudness($event, 'lra_lu')"
            /></label>
          </div>
        </section>
        <section class="min-w-0 space-y-3 rounded-lg border border-line bg-ground p-3">
          <h4 class="text-sm font-semibold">{{ t("processing.fades") }}</h4>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label class="min-w-0 text-sm font-medium"
              >{{ t("processing.fadeIn")
              }}<input
                :value="settings.fade_in_seconds"
                data-test="fade-in"
                type="number"
                min="0"
                max="60"
                step="0.1"
                class="field mt-1"
                @input="setNumber($event, (v) => (settings.fade_in_seconds = v))"
            /></label>
            <label class="min-w-0 text-sm font-medium"
              >{{ t("processing.fadeOut")
              }}<input
                :value="settings.fade_out_seconds"
                data-test="fade-out"
                type="number"
                min="0"
                max="60"
                step="0.1"
                class="field mt-1"
                @input="setNumber($event, (v) => (settings.fade_out_seconds = v))"
            /></label>
          </div>
        </section>
        <section class="min-w-0 space-y-3 rounded-lg border border-line bg-ground p-3">
          <h4 class="text-sm font-semibold">{{ t("processing.introOutro") }}</h4>
          <div v-for="edge in (['intro', 'outro'] as const)" :key="edge" class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label class="min-w-0 text-sm font-medium"
              >{{ t(`processing.${edge}`)
              }}<select :value="reference(edge) ?? ''" :data-test="edge" class="field mt-1" @change="onAsset($event, edge)">
                <option value="">{{ t("processing.none") }}</option>
                <option v-for="option in assetOptions(edge)" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select></label
            >
            <label class="min-w-0 text-sm font-medium"
              >{{ t(edge === "intro" ? "processing.introTransition" : "processing.outroTransition")
              }}<input
                :value="transitionSeconds(settings, edge) ?? ''"
                :data-test="`${edge}-transition`"
                type="number"
                min="0"
                max="60"
                step="0.1"
                class="field mt-1"
                :disabled="!reference(edge)"
                @input="onTransition($event, edge)"
            /></label>
          </div>
        </section>
      </template>
      <div>
        <label :for="`${id}-json`" class="mb-1.5 block text-sm font-medium">{{ t("processing.advanced") }}</label>
        <textarea
          :id="`${id}-json`"
          :value="json"
          data-test="json"
          rows="14"
          spellcheck="false"
          class="field font-mono text-xs"
          :aria-invalid="jsonError ? true : undefined"
          :aria-describedby="`${id}-json-help`"
          @input="onJson"
        />
        <p :id="`${id}-json-help`" class="mt-2 text-sm text-muted">{{ t("processing.advanced.hint") }}</p>
        <p v-if="jsonError" data-test="json-error" class="mt-1 text-sm break-words text-danger">{{ jsonError }}</p>
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
