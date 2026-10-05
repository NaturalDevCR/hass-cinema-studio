import { ref } from "vue";

export type ToastKind = "info" | "success" | "error";
export type Toast = { id: number; message: string; kind: ToastKind };

const MAX_TOASTS = 4;
/** Errors stay longer: they usually need to be read, not just noticed. */
const LIFETIME_MS: Record<ToastKind, number> = { info: 3500, success: 3500, error: 7000 };

const toasts = ref<Toast[]>([]);
let nextId = 1;

function dismiss(id: number): void {
  toasts.value = toasts.value.filter((toast) => toast.id !== id);
}

function push(message: string, kind: ToastKind = "info"): void {
  const id = nextId++;
  toasts.value = [...toasts.value, { id, message, kind }].slice(-MAX_TOASTS);
  setTimeout(() => dismiss(id), LIFETIME_MS[kind]);
}

/** Shared toast queue; `ToastStack` renders it once at the app root. */
export function useToast() {
  return { push, dismiss, toasts };
}
