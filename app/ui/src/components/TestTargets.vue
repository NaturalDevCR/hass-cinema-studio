<script setup lang="ts">
import { ref } from "vue";
import type { Settings, TestTarget } from "@/api/types";
import { useSettingsSave } from "@/composables/useSettingsSave";
import { useI18n } from "@/i18n";
const props = defineProps<{ settings: Settings }>();
const { t } = useI18n();
const { pending, error, save } = useSettingsSave();
const label = ref("");
const entity = ref("");
const validation = ref<string | null>(null);
const protectedEntities = ref(props.settings.protected_entities.join("\n"));
function targetIsValid(id: string): boolean {
  if (!/^media_player\.[a-z0-9_]+$/.test(id)) { validation.value = t("system.targetOnlyMediaPlayer"); return false; }
  if (props.settings.protected_entities.includes(id)) { validation.value = t("system.targetProtected", { entity: id }); return false; }
  return true;
}
async function add() {
  validation.value = null;
  const id = entity.value.trim();
  if (!label.value.trim()) { validation.value = t("system.targetLabelRequired"); return; }
  if (!targetIsValid(id)) return;
  const targets: TestTarget[] = [...props.settings.test_targets, { id: crypto.randomUUID(), label: label.value.trim(), entity_id: id }];
  if (await save({ test_targets: targets })) { label.value = ""; entity.value = ""; }
}
async function remove(id: string) { await save({ test_targets: props.settings.test_targets.filter((target) => target.id !== id) }); }
async function saveProtected() {
  const list = [...new Set(protectedEntities.value.split(/\s+/).map((value) => value.trim()).filter(Boolean))];
  if (list.some((value) => !/^(media_player|cover|switch|light)\.[a-z0-9_]+$/.test(value))) { validation.value = t("system.protectedInvalid"); return; }
  validation.value = null;
  await save({ protected_entities: list });
}
</script>
<template>
  <section class="panel min-w-0 space-y-4" aria-labelledby="targets-heading" :aria-busy="pending">
    <h3 id="targets-heading" class="font-semibold">{{ t("system.testTargets") }}</h3>
    <ul class="space-y-2"><li v-for="target in settings.test_targets" :key="target.id" class="flex items-center justify-between gap-2"><span>{{ target.label }} <span class="text-muted">({{ target.entity_id }})</span></span><button class="btn-ghost min-h-11!" :aria-label="t('system.removeTarget', { label: target.label })" :disabled="pending" @click="remove(target.id)">{{ t("common.delete") }}</button></li></ul>
    <form class="grid gap-2 sm:grid-cols-2" @submit.prevent="add"><label class="text-sm">{{ t("system.targetLabel") }}<input id="target-label" v-model="label" class="field mt-1" required /></label><label class="text-sm">{{ t("system.targetEntity") }}<input id="target-entity" v-model="entity" class="field mt-1" required placeholder="media_player.living_room" /></label><button class="btn-primary min-h-11! sm:col-span-2" type="submit" :disabled="pending">{{ t("system.addTarget") }}</button></form>
    <div><label for="protected-entities" class="text-sm">{{ t("system.protectedEntities") }}</label><textarea id="protected-entities" v-model="protectedEntities" class="field mt-1 min-h-20" /><button class="btn mt-2 min-h-11!" :disabled="pending" @click="saveProtected">{{ t("common.save") }}</button></div>
    <p v-if="validation" role="alert" class="text-sm text-warn">{{ validation }}</p><p v-if="error" role="alert" class="text-sm text-danger">{{ error }}</p>
  </section>
</template>
