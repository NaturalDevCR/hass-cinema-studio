<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Sheet from "./Sheet.vue";
import { ui, messageOf } from "@/api/client";
import { useStudio } from "@/composables/useStudio";
import { useI18n } from "@/i18n";
const props = defineProps<{
  open: boolean;
  clipId: string;
  previewAvailable: boolean;
  renderAvailable: boolean;
}>();
const emit = defineEmits<{ close: [] }>();
const { state } = useStudio(),
  { t } = useI18n();
const targets = computed(
  () =>
    state.value?.settings.test_targets.filter(
      (target) =>
        target.entity_id.startsWith("media_player.") &&
        !state.value!.settings.protected_entities.includes(target.entity_id),
    ) ?? [],
);
const targetId = ref(""),
  source = ref<"preview" | "render">("render"),
  busy = ref(false),
  error = ref<string | null>(null),
  sent = ref(false);
watch(
  () => props.open,
  () => {
    targetId.value = targets.value[0]?.id ?? "";
    source.value = props.renderAvailable ? "render" : "preview";
    error.value = null;
    sent.value = false;
  },
  { immediate: true },
);
watch(targets, (list) => {
  if (!list.some((target) => target.id === targetId.value))
    targetId.value = list[0]?.id ?? "";
});
const available = computed(() =>
  source.value === "preview" ? props.previewAvailable : props.renderAvailable,
);
async function send() {
  if (
    busy.value ||
    !available.value ||
    !targets.value.some((t) => t.id === targetId.value)
  )
    return;
  busy.value = true;
  error.value = null;
  sent.value = false;
  try {
    await ui.clips.test(props.clipId, {
      target_id: targetId.value,
      source: source.value,
    });
    sent.value = true;
  } catch (cause) {
    error.value = messageOf(cause);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <Sheet :open="open" :title="t('clipEditor.test')" @close="emit('close')">
    <RouterLink v-if="!targets.length" to="/system" class="text-accent">{{
      t("clipEditor.noTargets")
    }}</RouterLink>
    <div v-else class="space-y-4">
      <label class="block"
        >{{ t("clipEditor.target")
        }}<select
          data-test="test-target"
          v-model="targetId"
          class="field w-full"
        >
          <option v-for="target in targets" :key="target.id" :value="target.id">
            {{ target.label }}
          </option>
        </select></label
      >
      <label class="block"
        >{{ t("clipEditor.testSource")
        }}<select v-model="source" class="field w-full">
          <option value="render" :disabled="!renderAvailable">
            {{ t("clipEditor.render") }}
          </option>
          <option value="preview" :disabled="!previewAvailable">
            {{ t("clipEditor.preview") }}
          </option>
        </select></label
      >
      <p v-if="error" role="alert" class="text-danger">{{ error }}</p>
      <p v-if="sent" role="status">{{ t("clipEditor.sent") }}</p>
    </div>
    <template #footer
      ><button
        data-test="send-test"
        class="btn-primary"
        :disabled="busy || !targetId || !available"
        @click="send"
      >
        {{ t("clipEditor.send") }}
      </button></template
    >
  </Sheet>
</template>
