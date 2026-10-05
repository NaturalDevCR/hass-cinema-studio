import { ref } from "vue";
import { messageOf } from "@/api/client";
import { useStudio } from "./useStudio";
import { useToast } from "./useToast";
import { translate } from "@/i18n";

/** Shared save lifecycle for the Organize forms; API details stay in each form. */
export function useFormMutation() {
  const pending = ref(false);
  const error = ref<string | null>(null);
  async function save<T>(action: () => Promise<T>, saved: (result: T) => void): Promise<void> {
    if (pending.value) return;
    pending.value = true;
    error.value = null;
    try {
      const result = await action();
      // The change is already saved: a failed refresh must not turn this into an error the user retries.
      await Promise.allSettled([useStudio().refresh()]);
      useToast().push(translate("organize.saved"), "success");
      saved(result);
    } catch (cause) {
      error.value = messageOf(cause);
    } finally {
      pending.value = false;
    }
  }
  return { pending, error, save };
}
