<script setup lang="ts">
import { ref, useId, watch } from "vue";
import { ui } from "@/api/client";
import type { Collection, PlaybackMode } from "@/api/types";
import { useI18n } from "@/i18n";
import { useFormMutation } from "@/composables/useFormMutation";
import { useStudio } from "@/composables/useStudio";
import { useToast } from "@/composables/useToast";
import ColorPicker from "./ColorPicker.vue";
import IconPicker from "./IconPicker.vue";
const props = defineProps<{ collection?: Collection }>();
const emit = defineEmits<{
  saved: [collection: Collection];
  busy: [pending: boolean];
}>();
const { t, tp } = useI18n();
const id = useId();
const { procProfiles } = useStudio();
const modes: PlaybackMode[] = ["random", "sequential", "custom"];
// After a successful create the form edits that collection, so a retry cannot create a duplicate.
const current = ref(props.collection);
const name = ref(props.collection?.name ?? "");
const color = ref(props.collection?.color ?? "#f59e0b");
const colorValid = ref(true);
const icon = ref(props.collection?.icon ?? "mdi:filmstrip-box");
const mode = ref<PlaybackMode>(props.collection?.playback_mode ?? "random");
const profileId = ref(props.collection?.processing_profile_id ?? procProfiles.value[0]?.id ?? "");
const enabled = ref(props.collection?.enabled ?? true);
// Profiles may still be loading when the form opens: pick the first one as soon as it arrives.
watch(
  procProfiles,
  (list) => {
    if (!profileId.value && list[0]) profileId.value = list[0].id;
  },
  { flush: "sync" },
);
const { pending, error, save } = useFormMutation();
watch(pending, (value) => emit("busy", value), { flush: "sync" });
async function submit(): Promise<void> {
  if (pending.value) return;
  if (!name.value.trim()) {
    error.value = t("form.nameRequired");
    return;
  }
  if (!colorValid.value) {
    error.value = t("form.colorInvalid");
    return;
  }
  const fields = {
    name: name.value.trim(),
    color: color.value,
    icon: icon.value,
    playback_mode: mode.value,
    ...(profileId.value ? { processing_profile_id: profileId.value } : {}),
  };
  await save(
    async () => {
      if (!current.value) {
        current.value = await ui.collections.create(fields);
        return { collection: current.value, affected_clip_ids: [] as string[] };
      }
      const result = await ui.collections.update(current.value.id, { ...fields, enabled: enabled.value });
      current.value = result.collection;
      return result;
    },
    ({ collection, affected_clip_ids }) => {
      if (affected_clip_ids.length) useToast().push(tp("profile.rerendering", affected_clip_ids.length), "success");
      emit("saved", collection);
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
      <ColorPicker v-model="color" @valid="colorValid = $event" />
      <IconPicker v-model="icon" />
      <fieldset class="min-w-0">
        <legend class="mb-2 text-sm font-medium">{{ t("collection.mode") }}</legend>
        <div class="space-y-2">
          <label
            v-for="option in modes"
            :key="option"
            class="flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border border-line bg-ground p-3 has-[:checked]:border-accent"
          >
            <input
              v-model="mode"
              type="radio"
              :name="`${id}-mode`"
              :value="option"
              :data-test="`mode-${option}`"
              class="mt-1 accent-accent"
            />
            <span class="min-w-0">
              <span class="block text-sm font-medium">{{ t(`collection.mode.${option}`) }}</span>
              <span :data-test="`mode-${option}-hint`" class="block text-sm text-muted">{{
                t(`collection.mode.${option}.hint`)
              }}</span>
            </span>
          </label>
        </div>
      </fieldset>
      <div>
        <label :for="`${id}-profile`" class="mb-1.5 block text-sm font-medium">{{ t("collection.profile") }}</label
        ><select :id="`${id}-profile`" v-model="profileId" data-test="profile" class="field">
          <option v-for="profile in procProfiles" :key="profile.id" :value="profile.id">{{ profile.name }}</option>
          <option v-if="profileId && !procProfiles.some((p) => p.id === profileId)" :value="profileId">
            {{ t("collection.profile.missing", { id: profileId }) }}
          </option>
        </select>
        <p class="mt-2 text-sm text-muted">{{ t("collection.profile.hint") }}</p>
      </div>
      <label v-if="collection" class="flex min-h-11 items-start gap-3">
        <input v-model="enabled" type="checkbox" data-test="enabled" class="mt-1 size-5 accent-accent" />
        <span class="min-w-0">
          <span class="block text-sm font-medium">{{ t("collection.enabled") }}</span>
          <span class="block text-sm text-muted">{{ t("collection.enabled.hint") }}</span>
        </span>
      </label>
    </fieldset>
    <p v-if="error" role="alert" class="text-sm break-words text-danger">
      {{ error }}
    </p>
    <button type="submit" class="btn-primary w-full" :disabled="pending">
      {{ pending ? t("common.loading") : t("common.save") }}
    </button>
  </form>
</template>
