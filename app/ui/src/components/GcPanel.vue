<script setup lang="ts">
import { ref } from "vue";
import type { ConsumerInfo, State } from "@/api/types";
import { ui, messageOf } from "@/api/client";
import { useStudio } from "@/composables/useStudio";
import { useToast } from "@/composables/useToast";
import { useI18n } from "@/i18n";
import { formatDateTime } from "@/lib/format";
const props = defineProps<{ state: State; consumers: ConsumerInfo[] }>();
const { t, locale } = useI18n();
const pending = ref(false);
const error = ref<string | null>(null);
async function run() {
  if (pending.value) return;
  pending.value = true; error.value = null;
  try {
    const result = await ui.gcRun();
    await useStudio().refresh({ force: true });
    useToast().push(result.halted_reason ?? t("system.gcDeleted", { count: result.deleted }), result.halted_reason ? "error" : "success");
  } catch (cause) { error.value = messageOf(cause); }
  finally { pending.value = false; }
}
</script>
<template>
  <section class="panel min-w-0 space-y-4" aria-labelledby="gc-heading" :aria-busy="pending">
    <h3 id="gc-heading" class="font-semibold">{{ t("system.gc") }}</h3>
    <p :class="state.gc.enabled ? 'text-ok' : 'text-warn'">{{ state.gc.enabled ? t("system.gcEnabled") : t("system.gcHalted") }}</p>
    <p v-if="state.gc.halted_reason" role="alert" class="text-sm text-warn">{{ state.gc.halted_reason }}</p>
    <dl class="grid grid-cols-2 gap-2 text-sm"><div><dt class="text-muted">{{ t("system.gcLastRun") }}</dt><dd>{{ formatDateTime(state.gc.last_run_at, locale) }}</dd></div><div><dt class="text-muted">{{ t("system.gcDeletedLast") }}</dt><dd>{{ state.gc.deleted_last_run }}</dd></div></dl>
    <button class="btn min-h-11!" :disabled="pending" @click="run">{{ t("system.gcRun") }}</button>
    <p v-if="error" role="alert" class="text-sm text-danger">{{ error }}</p>
    <div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr><th>{{ t("system.consumer") }}</th><th>{{ t("system.filePresent") }}</th><th>{{ t("system.heldRevision") }}</th><th>{{ t("system.pins") }}</th></tr></thead><tbody><tr v-for="consumer in consumers" :key="consumer.consumer_id"><td>{{ consumer.consumer_id }}</td><td>{{ consumer.file_present ? t("common.yes") : t("common.no") }}</td><td>{{ consumer.held_revision ?? "—" }}</td><td>{{ consumer.pins }}</td></tr><tr v-if="!consumers.length"><td colspan="4" class="py-2 text-muted">{{ t("system.noConsumers") }}</td></tr></tbody></table></div>
  </section>
</template>
