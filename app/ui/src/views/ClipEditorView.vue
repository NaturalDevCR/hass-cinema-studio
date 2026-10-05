<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  toRef,
  watch,
} from "vue";
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRouter } from "vue-router";
import Sheet from "@/components/Sheet.vue";
import VideoStage from "@/components/VideoStage.vue";
import FilmstripTimeline from "@/components/FilmstripTimeline.vue";
import TransportBar from "@/components/TransportBar.vue";
import TestDeviceDialog from "@/components/TestDeviceDialog.vue";
import ProfilePicker from "@/components/ProfilePicker.vue";
import { useClipEditor } from "@/composables/useClipEditor";
import { useStudio } from "@/composables/useStudio";
import { useJobs } from "@/composables/useJobs";
import { useConfirm } from "@/composables/useConfirm";
import { useToast } from "@/composables/useToast";
import { useI18n } from "@/i18n";
import type { MediaKind } from "@/api/types";
import { UPLOAD_EXTENSIONS } from "@/composables/useUpload";
import { trimmedLength } from "@/lib/recipe";
import { formatTimecode, formatLufs, formatDateTime } from "@/lib/format";
const props = defineProps<{ id: string }>();
const { t, locale } = useI18n(),
  router = useRouter(),
  studio = useStudio(),
  jobs = useJobs();
const editor = useClipEditor(toRef(props, "id"));
const {
  clip,
  recipe,
  details,
  dirty,
  problems,
  saving,
  previewReady,
  previewPending,
  error,
  loading,
  previewVersion,
  replacing,
  uploadProgress,
} = editor;
const stage = ref<InstanceType<typeof VideoStage> | null>(null),
  position = ref(0),
  playing = ref(false),
  loop = ref(false),
  source = ref<MediaKind>("original");
const testOpen = ref(false),
  invalidTrim = ref(false);
const timeline = ref<InstanceType<typeof FilmstripTimeline> | null>(null),
  fileInput = ref<HTMLInputElement | null>(null);
const duration = computed(() => clip.value?.original?.duration ?? 0);
const collection = computed(() =>
  studio.collectionById(details.value.collection_id),
);
const profile = computed(() =>
  studio.procProfileById(collection.value?.processing_profile_id),
);
const fadeIn = computed(
  () => recipe.value.fade_in ?? profile.value?.settings.fade_in_seconds ?? 1,
);
const fadeOut = computed(
  () =>
    recipe.value.fade_out ?? profile.value?.settings.fade_out_seconds ?? 1.5,
);
const canSave = computed(
  () =>
    dirty.value &&
    !problems.value.length &&
    !invalidTrim.value &&
    !saving.value &&
    !replacing.value &&
    !!details.value.title?.trim() &&
    !!details.value.collection_id &&
    !!clip.value?.original,
);
const activeJobs = computed(() =>
  jobs.active.value.filter((job) => job.clip_id === props.id),
);
const missingAssets = computed(() =>
  studio.assets.value.some(
    (asset) =>
      asset.status === "missing" &&
      [
        profile.value?.settings.intro_reference,
        profile.value?.settings.outro_reference,
      ].includes(asset.filename),
  ),
);
watch(previewReady, async (ready) => {
  if (ready && previewVersion.value) {
    source.value = "preview";
    await nextTick();
    void stage.value?.toggle();
  } else if (!ready && source.value === "preview") source.value = "original";
});
watch(clip, (next) => {
  if (next && !next.original && next.render && source.value === "original")
    source.value = "render";
});
watch(
  () => props.id,
  () => {
    source.value = "original";
    testOpen.value = false;
    invalidTrim.value = false;
  },
);
async function guard() {
  if (saving.value || replacing.value) {
    useToast().push(t("clipEditor.busy"), "info");
    return false;
  }
  return (
    (!dirty.value && !invalidTrim.value) ||
    useConfirm().confirm({ title: t("clipEditor.discard") })
  );
}
onBeforeRouteLeave(guard);
onBeforeRouteUpdate((to, from) =>
  to.params.id !== from.params.id ? guard() : true,
);
function beforeUnload(e: BeforeUnloadEvent) {
  if (dirty.value || invalidTrim.value || replacing.value) {
    e.preventDefault();
    e.returnValue = "";
  }
}
function shortcut(e: KeyboardEvent) {
  if (
    testOpen.value ||
    useConfirm().request.value ||
    e.defaultPrevented ||
    e.repeat ||
    e.isComposing ||
    e.ctrlKey ||
    e.metaKey ||
    e.altKey
  )
    return;
  if (
    e.target instanceof HTMLElement &&
    e.target.closest('input,textarea,select,button,a,[contenteditable="true"]')
  )
    return;
  if (e.key === " ") {
    e.preventDefault();
    void stage.value?.toggle();
  }
}
onMounted(() => {
  document.addEventListener("keydown", shortcut);
  window.addEventListener("beforeunload", beforeUnload);
});
onBeforeUnmount(() => {
  document.removeEventListener("keydown", shortcut);
  window.removeEventListener("beforeunload", beforeUnload);
});
async function replaceSource(e: Event) {
  const input = e.target as HTMLInputElement,
    file = input.files?.[0];
  if (!file) return;
  await editor.replaceSource(file);
  source.value = "original";
  input.value = "";
}
async function revert() {
  editor.resetRecipe();
  invalidTrim.value = false;
  await timeline.value?.resync();
}
</script>
<template>
  <Sheet
    :open="true"
    wide
    :title="clip?.title ?? t('editor.title')"
    @close="router.push({ name: 'library' })"
  >
    <p v-if="loading" aria-busy="true">{{ t("clipEditor.loading") }}</p>
    <p v-else-if="!clip">{{ t("clipEditor.notFound") }}</p>
    <div
      v-else
      class="grid gap-6 lg:grid-cols-2"
      :inert="saving || replacing"
    >
      <div class="min-w-0 space-y-4">
        <div
          class="flex gap-2"
          role="group"
          :aria-label="t('clipEditor.testSource')"
        >
          <button
            v-for="kind in ['original', 'preview', 'render'] as const"
            :key="kind"
            class="btn"
            :aria-pressed="source === kind"
            :disabled="
              kind === 'original'
                ? !clip.original
                : kind === 'preview'
                  ? !previewReady
                  : !clip.render
            "
            @click="source = kind"
          >
            {{ t(`clipEditor.${kind}`) }}
          </button>
        </div>
        <VideoStage
          v-if="clip.original || source !== 'original'"
          :key="`${id}:${source}:${previewVersion}`"
          ref="stage"
          :clip="clip"
          :recipe="recipe"
          :source="source"
          :preview-version="previewVersion"
          :loop="loop"
          :fade-in="fadeIn"
          :fade-out="fadeOut"
          @position="position = $event"
          @playing="playing = $event"
          @crop="recipe.crop = $event"
        />
        <FilmstripTimeline
          v-if="clip.original"
          ref="timeline"
          :key="clip.original.sha256"
          :clip-id="id"
          :duration="duration"
          :fps="clip.original.fps"
          :recipe="recipe"
          :position="source === 'original' ? position : 0"
          :bust="clip.original.sha256"
          @trim="
            (start, end) => {
              recipe.trim_start = start;
              recipe.trim_end = end;
            }
          "
          @seek="
            (time) => {
              source = 'original';
              $nextTick(() => stage?.seek(time));
            }
          "
          @invalid="invalidTrim = $event"
        />
        <TransportBar
          :playing="playing"
          :loop="loop"
          :position="position"
          :length="trimmedLength(recipe, duration)"
          :disabled="!clip.original && source === 'original'"
          @play="stage?.toggle()"
          @loop="loop = !loop"
          @jump="stage?.jump($event)"
        />
        <ul v-if="problems.length" role="alert" class="text-danger">
          <li v-for="problem in problems" :key="problem">{{ t(problem) }}</li>
        </ul>
        <section class="space-y-2 rounded border border-line p-3">
          <h3 class="font-semibold">{{ t("clipEditor.published") }}</h3>
          <dl v-if="clip.render" class="grid grid-cols-2 gap-2 text-sm">
            <dt>{{ t("clipEditor.render") }}</dt>
            <dd>r{{ clip.render.n }}</dd>
            <dt>{{ t("clipEditor.duration") }}</dt>
            <dd>{{ formatTimecode(clip.render.duration) }}</dd>
            <dt>{{ t("clipEditor.content") }}</dt>
            <dd>
              {{ formatTimecode(clip.render.content_start) }} /
              {{ formatTimecode(clip.render.content_end) }}
            </dd>
            <dt>{{ t("clipEditor.lufs") }}</dt>
            <dd>{{ formatLufs(clip.render.integrated_lufs) }}</dd>
            <dt>{{ t("clipEditor.timing") }}</dt>
            <dd>{{ t(`clipEditor.timing.${clip.render.timing_source}`) }}</dd>
            <dt>{{ t("clipEditor.date") }}</dt>
            <dd>{{ formatDateTime(clip.render.published_at, locale) }}</dd>
          </dl>
          <p v-if="clip.render_pending || clip.status === 'rendering'">
            {{ t("clipEditor.pending") }}
          </p>
          <div v-for="job in activeJobs" :key="job.id">
            <span>{{ job.kind }}</span
            ><progress class="w-full" :value="job.progress" max="1" />
          </div>
          <RouterLink
            v-if="missingAssets"
            :to="{ path: '/organize', query: { tab: 'assets' } }"
            class="text-accent"
            >{{
            t("clipEditor.missing")
          }}</RouterLink>
          <template v-if="clip.needs_source">
            <button
              type="button"
              data-test="replace-source"
              class="btn"
              :disabled="replacing"
              @click="fileInput?.click()"
            >
              {{ t("clipEditor.replace") }}
            </button>
            <input
              ref="fileInput"
              type="file"
              class="sr-only"
              tabindex="-1"
              :aria-label="t('clipEditor.replaceHint')"
              :accept="UPLOAD_EXTENSIONS.join(',')"
              :disabled="replacing"
              @change="replaceSource"
            />
          </template>
          <progress v-if="replacing" :value="uploadProgress" max="1" />
          <p v-if="clip.error" role="alert" class="text-danger">
            {{ clip.error }}
          </p>
        </section>
      </div>
      <div class="space-y-4">
        <div
          v-for="edge in ['fade_in', 'fade_out'] as const"
          :key="edge"
          class="space-y-1"
        >
          <label class="block"
            >{{
              t(
                edge === "fade_in" ? "clipEditor.fadeIn" : "clipEditor.fadeOut",
              )
            }}<input
              v-if="recipe[edge] !== null"
              v-model.number="recipe[edge]"
              class="field w-full"
              type="number"
              min="0"
              step="0.1"
          /></label>
          <label
            ><input
              type="checkbox"
              :checked="recipe[edge] === null"
              @change="
                recipe[edge] = ($event.target as HTMLInputElement).checked
                  ? null
                  : edge === 'fade_in'
                    ? fadeIn
                    : fadeOut
              "
            />
            {{
              t("clipEditor.profileFade", {
                n:
                  edge === "fade_in"
                    ? (profile?.settings.fade_in_seconds ?? 1)
                    : (profile?.settings.fade_out_seconds ?? 1.5),
              })
            }}</label
          >
        </div>
        <label class="block"
          >{{ t("clipEditor.gain") }}: {{ recipe.gain_db
          }}<input
            v-model.number="recipe.gain_db"
            class="w-full accent-amber-500"
            type="range"
            min="-24"
            max="24"
            step="0.5"
        /></label>
        <ProfilePicker v-model="recipe.profile_id" />
        <p class="text-xs text-muted">{{ t("clipEditor.profileHint") }}</p>
        <label
          v-for="edge in ['lead_in', 'tail_out'] as const"
          :key="edge"
          class="block"
          >{{ t(edge === "lead_in" ? "clipEditor.lead" : "clipEditor.tail")
          }}<input
            v-model.number="recipe[edge]"
            class="field w-full"
            type="number"
            min="0"
            max="10"
            step="0.1"
        /></label>
        <label class="block"
          >{{ t("clipEditor.collection")
          }}<select v-model="details.collection_id" class="field w-full">
            <option
              v-for="c in studio.collections.value"
              :key="c.id"
              :value="c.id"
            >
              {{ c.name }}
            </option>
          </select></label
        >
        <label class="block"
          >{{ t("clipEditor.name")
          }}<input
            v-model="details.title"
            data-test="title"
            class="field w-full"
            :aria-invalid="!details.title?.trim()"
            :aria-describedby="details.title?.trim() ? undefined : 'title-error'" /></label>
        <p
          v-if="!details.title?.trim()"
          id="title-error"
          data-test="title-error"
          role="alert"
          class="text-danger"
        >
          {{ t("clipEditor.titleRequired") }}
        </p>
        <label class="block"
          ><input v-model="details.enabled" type="checkbox" />
          {{ t("clipEditor.enabled") }}</label
        >
        <label class="block"
          >{{ t("clipEditor.notes")
          }}<textarea v-model="details.notes" class="field w-full" />
        </label>
      </div>
    </div>
    <p v-if="error" role="alert" class="text-danger">{{ error }}</p>
    <template v-if="clip" #footer
      ><div class="flex flex-wrap gap-2" :inert="saving || replacing">
        <button
          data-test="preview-render"
          class="btn"
          :disabled="
            !clip.original ||
            problems.length > 0 ||
            invalidTrim ||
            previewPending ||
            saving
          "
          @click="editor.previewRender"
        >
          {{ t("clipEditor.previewAction") }}
        </button>
        <button data-test="test-device" class="btn" @click="testOpen = true">
          {{ t("clipEditor.test") }}
        </button>
        <button
          data-test="save"
          class="btn-primary"
          :disabled="!canSave"
          @click="editor.save"
        >
          {{ t("clipEditor.save") }}
        </button>
        <button
          data-test="revert"
          class="btn"
          :disabled="(!dirty && !invalidTrim) || saving"
          @click="revert"
        >
          {{ t("clipEditor.reset") }}
        </button>
      </div></template
    >
  </Sheet>
  <TestDeviceDialog
    :open="testOpen"
    :clip-id="id"
    :preview-available="previewReady"
    :render-available="!!clip?.render"
    @close="testOpen = false"
  />
</template>
