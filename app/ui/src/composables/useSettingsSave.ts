import { ref } from "vue";
import { ui, messageOf } from "@/api/client";
import type { Settings } from "@/api/types";
import { useStudio } from "./useStudio";
import { useToast } from "./useToast";
import { useI18n } from "@/i18n";
// Each PUT replaces all settings. Serialize panel saves and merge at execution time.
let tail: Promise<void> = Promise.resolve();
export function useSettingsSave() {
  const studio = useStudio();
  const { t } = useI18n();
  const pending = ref(false);
  const error = ref<string | null>(null);
  async function save(patch: Partial<Settings>): Promise<boolean> {
    if (pending.value || !studio.state.value) return false;
    pending.value = true;
    error.value = null;
    let success = false;
    const run = tail.then(async () => {
      try {
        const settings = await ui.settings.put({ ...studio.state.value!.settings, ...patch });
        studio.applySettings(settings);
        useToast().push(t("system.saved"), "success");
        await studio.refresh({ force: true });
        success = true;
      } catch (cause) {
        error.value = messageOf(cause);
      }
    });
    tail = run.catch(() => {});
    try {
      await run;
    } finally {
      pending.value = false;
    }
    return success;
  }
  return { pending, error, save };
}
