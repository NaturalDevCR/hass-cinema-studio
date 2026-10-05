import { ref } from "vue";

export type ConfirmOptions = {
  title?: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Styles the confirm button as destructive and focuses Cancel first. */
  danger?: boolean;
};

export type ConfirmRequest = ConfirmOptions & { resolve: (answer: boolean) => void };

const request = ref<ConfirmRequest | null>(null);

/** Opens the app-wide `ConfirmDialog`. A new question cancels any unanswered one. */
function confirm(options: ConfirmOptions = {}): Promise<boolean> {
  request.value?.resolve(false);
  return new Promise<boolean>((resolve) => {
    request.value = { ...options, resolve };
  });
}

function answer(value: boolean): void {
  const current = request.value;
  if (!current) return;
  request.value = null;
  current.resolve(value);
}

/**
 * Promise-based confirmation: `if (await confirm({ title, danger: true })) ...`.
 * Needs a single `<ConfirmDialog />` mounted in App.vue.
 */
export function useConfirm() {
  return { confirm, request, answer };
}
