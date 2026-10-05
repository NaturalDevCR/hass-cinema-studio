<script setup lang="ts">
import { computed, ref, useId, watch } from "vue";
import { ui } from "@/api/client";
import type { Season } from "@/api/types";
import { useI18n, type MessageKey } from "@/i18n";
import { useFormMutation } from "@/composables/useFormMutation";
import { useStudio } from "@/composables/useStudio";
import ColorPicker from "./ColorPicker.vue";
import IconPicker from "./IconPicker.vue";
const props = defineProps<{ season?: Season }>();
const emit = defineEmits<{
  saved: [season: Season];
  busy: [pending: boolean];
}>();
const { t } = useI18n();
const id = useId();
const regular = props.season?.id === "regular";
// A season plays one collection; the built-in Regular season keeps its own and is not editable here.
const { collections } = useStudio();
const collectionId = ref(props.season?.collection_id ?? collections.value[0]?.id ?? "");
const name = ref(props.season?.name ?? "");
const color = ref(props.season?.color ?? "#34d399");
const colorValid = ref(true);
const icon = ref(props.season?.icon ?? "mdi:calendar-star");
const priority = ref<number | string>(props.season?.priority ?? 0);
const dates = ref({
  start: {
    month: Number(props.season?.start?.slice(0, 2) ?? 1),
    day: Number(props.season?.start?.slice(3) ?? 1),
  },
  end: {
    month: Number(props.season?.end?.slice(0, 2) ?? 12),
    day: Number(props.season?.end?.slice(3) ?? 31),
  },
});
const sides = ["start", "end"] as const;
const daysInMonth = (month: number) => new Date(2000, month, 0).getDate();
const dayOptions = computed(() => ({
  start: daysInMonth(dates.value.start.month),
  end: daysInMonth(dates.value.end.month),
}));
watch(
  () => [dates.value.start.month, dates.value.end.month],
  () => {
    for (const side of sides) dates.value[side].day = Math.min(dates.value[side].day, dayOptions.value[side]);
  },
  { flush: "sync" },
);
const monthName = (month: number) => t(`month.${month}` as MessageKey);
const dateString = (side: "start" | "end") =>
  `${String(dates.value[side].month).padStart(2, "0")}-${String(dates.value[side].day).padStart(2, "0")}`;
const { pending, error, save } = useFormMutation();
watch(pending, (value) => emit("busy", value), { flush: "sync" });
async function submit(): Promise<void> {
  if (pending.value) return;
  if (!name.value.trim()) {
    error.value = t("form.nameRequired");
    return;
  }
  if (!regular && !collectionId.value) {
    error.value = t("season.collectionRequired");
    return;
  }
  if (!colorValid.value) {
    error.value = t("form.colorInvalid");
    return;
  }
  const value = Number(priority.value);
  if (!regular && (priority.value === "" || !Number.isInteger(value) || value < -1000 || value > 1000)) {
    error.value = t("season.priorityInvalid");
    return;
  }
  const common = {
    name: name.value.trim(),
    color: color.value,
    icon: icon.value,
  };
  const dated = {
    ...common,
    start: dateString("start"),
    end: dateString("end"),
    priority: value,
    collection_id: collectionId.value,
  };
  await save(
    () => (props.season ? ui.seasons.update(props.season.id, regular ? common : dated) : ui.seasons.create(dated)),
    (season) => emit("saved", season),
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
      <p v-if="regular" class="text-sm text-muted">
        {{ t("season.regularHint") }}
      </p>
      <template v-else>
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <fieldset v-for="side in sides" :key="side" class="min-w-0">
            <legend class="mb-2 text-sm font-medium">
              {{ t(`season.${side}`) }}
            </legend>
            <div class="grid grid-cols-2 gap-2">
              <label class="min-w-0 text-sm text-muted"
                >{{ t("season.month")
                }}<select v-model.number="dates[side].month" :data-test="`${side}-month`" class="field mt-1">
                  <option v-for="month in 12" :key="month" :value="month">
                    {{ monthName(month) }}
                  </option>
                </select></label
              >
              <label class="min-w-0 text-sm text-muted"
                >{{ t("season.day")
                }}<select v-model.number="dates[side].day" :data-test="`${side}-day`" class="field mt-1">
                  <option v-for="day in dayOptions[side]" :key="day" :value="day">
                    {{ day }}
                  </option>
                </select></label
              >
            </div>
          </fieldset>
        </div>
        <p class="text-sm text-muted">{{ t("season.wrapHint") }}</p>
        <div>
          <label :for="`${id}-collection`" class="mb-1.5 block text-sm font-medium">{{ t("season.collection") }}</label
          ><select :id="`${id}-collection`" v-model="collectionId" data-test="collection" class="field">
            <option v-for="collection in collections" :key="collection.id" :value="collection.id">
              {{ collection.name }}
            </option>
          </select>
          <p class="mt-2 text-sm text-muted">{{ t("season.collectionHint") }}</p>
        </div>
        <div>
          <label :for="`${id}-priority`" class="mb-1.5 block text-sm font-medium">{{ t("season.priority") }}</label
          ><input
            :id="`${id}-priority`"
            v-model="priority"
            data-test="priority"
            type="number"
            min="-1000"
            max="1000"
            step="1"
            class="field"
            :aria-describedby="`${id}-priority-help`"
          />
          <p :id="`${id}-priority-help`" class="mt-2 text-sm text-muted">
            {{ t("season.priorityHint") }}
          </p>
        </div>
      </template>
    </fieldset>
    <p v-if="error" role="alert" class="text-sm break-words text-danger">
      {{ error }}
    </p>
    <button type="submit" class="btn-primary w-full" :disabled="pending">
      {{ pending ? t("common.loading") : t("common.save") }}
    </button>
  </form>
</template>
