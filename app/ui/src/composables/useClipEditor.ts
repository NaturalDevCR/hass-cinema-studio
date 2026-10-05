import { computed, onBeforeUnmount, ref, watch, type Ref } from "vue";
import { messageOf, ui } from "@/api/client";
import type { Clip, ClipPatch, Recipe } from "@/api/types";
import { defaultRecipe, recipesEqual, validateRecipe } from "@/lib/recipe";
import { clone } from "@/lib/processing";
import { useStudio } from "./useStudio";
import { useJobs } from "./useJobs";
import { uploadChunks, validateUploadFile } from "./useUpload";

export function useClipEditor(clipId: Ref<string>) {
  const studio = useStudio(),
    jobs = useJobs();
  const clip = ref<Clip | null>(null);
  const recipe = ref<Recipe>(
    defaultRecipe({ default_lead_in: 2, default_tail_out: 2 }),
  );
  const details = ref<ClipPatch>({});
  const loading = ref(true),
    saving = ref(false),
    error = ref<string | null>(null);
  const previewReady = ref(false),
    previewPending = ref(false),
    previewVersion = ref("");
  const previewJob = ref<string | null>(null);
  const replacing = ref(false),
    uploadProgress = ref(0);
  let previewRecipe: Recipe | null = null,
    release: (() => void) | undefined,
    generation = 0;
  const detailsDirty = computed(
    () =>
      !!clip.value &&
      (["title", "collection_id", "enabled", "notes"] as const).some(
        (k) => details.value[k] !== clip.value![k],
      ),
  );
  const dirty = computed(
    () =>
      !!clip.value &&
      (!recipesEqual(recipe.value, clip.value.recipe) || detailsDirty.value),
  );
  const problems = computed(() =>
    clip.value?.original
      ? validateRecipe(recipe.value, clip.value.original)
      : [],
  );
  function apply(next: Clip) {
    clip.value = next;
    recipe.value = clone(next.recipe);
    details.value = {
      title: next.title,
      collection_id: next.collection_id,
      enabled: next.enabled,
      notes: next.notes,
    };
  }
  watch(
    clipId,
    async (id) => {
      const current = ++generation;
      clip.value = null;
      loading.value = true;
      error.value = null;
      previewReady.value = false;
      previewPending.value = false;
      previewJob.value = null;
      previewVersion.value = "";
      previewRecipe = null;
      release?.();
      release = undefined;
      try {
        const next = await ui.clips.get(id);
        if (current === generation) {
          apply(next);
          // `has_preview` only says some preview exists on the server, not that it matches
          // this recipe, so it stays unknown until a preview is rendered in this session.
          previewRecipe = clone(next.recipe);
        }
      } catch (cause) {
        if (current === generation) error.value = messageOf(cause);
      } finally {
        if (current === generation) loading.value = false;
      }
    },
    { immediate: true },
  );
  watch(studio.clips, (list) => {
    const next = list.find((c) => c.id === clipId.value);
    if (next && clip.value)
      clip.value = {
        ...next,
        recipe: clip.value.recipe,
        title: clip.value.title,
        collection_id: clip.value.collection_id,
        enabled: clip.value.enabled,
        notes: clip.value.notes,
      };
  });
  watch(
    recipe,
    () => {
      if (previewRecipe && !recipesEqual(recipe.value, previewRecipe))
        previewReady.value = false;
    },
    { deep: true },
  );
  watch(jobs.jobs, (list) => {
    const job = list.find((j) => j.id === previewJob.value);
    if (!job || !["done", "failed"].includes(job.status)) return;
    previewPending.value = false;
    previewJob.value = null;
    release?.();
    release = undefined;
    if (job.status === "failed") error.value = job.error;
    else if (previewRecipe && recipesEqual(recipe.value, previewRecipe)) {
      previewVersion.value = job.id;
      previewReady.value = true;
    }
  });
  async function save() {
    if (saving.value || !dirty.value || problems.value.length || !clip.value)
      return;
    saving.value = true;
    error.value = null;
    const id = clipId.value,
      current = generation;
    const snapshot = clone(recipe.value),
      metadata = clone(details.value);
    try {
      let next = clip.value;
      if (detailsDirty.value) next = await ui.clips.update(id, metadata);
      if (!recipesEqual(snapshot, clip.value.recipe))
        next = (await ui.clips.putRecipe(id, snapshot)).clip;
      if (current === generation) {
        // Keep edits made while the request was in flight, but advance the saved baseline.
        const draft = clone(recipe.value),
          detailDraft = clone(details.value);
        const recipeChanged = !recipesEqual(draft, snapshot);
        const detailsChanged =
          JSON.stringify(detailDraft) !== JSON.stringify(metadata);
        apply(next);
        if (recipeChanged) recipe.value = draft;
        if (detailsChanged) details.value = detailDraft;
        await Promise.all([studio.refreshClips(), jobs.refresh()]);
      }
    } catch (cause) {
      if (current === generation) error.value = messageOf(cause);
    } finally {
      saving.value = false;
    }
  }
  async function previewRender() {
    if (
      previewPending.value ||
      saving.value ||
      problems.value.length ||
      !clip.value?.original
    )
      return;
    previewPending.value = true;
    previewReady.value = false;
    error.value = null;
    const current = generation;
    previewRecipe = clone(recipe.value);
    release = jobs.suppressPreviewToast(clipId.value);
    try {
      const { job } = await ui.clips.preview(clipId.value, previewRecipe);
      if (current === generation) {
        previewJob.value = job.id;
        await jobs.refresh();
      }
    } catch (cause) {
      if (current === generation) {
        error.value = messageOf(cause);
        previewPending.value = false;
        release?.();
        release = undefined;
      }
    }
  }
  /** Uploads a replacement source (chunked, like a new upload) and adopts the repaired clip. */
  async function replaceSource(file: File) {
    if (replacing.value || !clip.value) return;
    const id = clipId.value,
      current = generation;
    replacing.value = true;
    error.value = null;
    uploadProgress.value = 0;
    try {
      const invalid = validateUploadFile(file);
      if (invalid) throw new Error(invalid);
      const uploadId = await uploadChunks(file, (n) => (uploadProgress.value = n));
      const next = await ui.clips.replaceSource(id, uploadId);
      if (current === generation) {
        apply(next);
        previewReady.value = false;
        await Promise.all([studio.refreshClips(), jobs.refresh()]);
      }
    } catch (cause) {
      if (current === generation) error.value = messageOf(cause);
    } finally {
      replacing.value = false;
    }
  }
  function resetRecipe() {
    if (clip.value) recipe.value = clone(clip.value.recipe);
  }
  onBeforeUnmount(() => {
    generation++;
    release?.();
  });
  return {
    clip,
    recipe,
    details,
    dirty,
    problems,
    saving,
    save,
    previewRender,
    resetRecipe,
    replaceSource,
    replacing,
    uploadProgress,
    previewReady,
    previewPending,
    previewVersion,
    error,
    loading,
  };
}
