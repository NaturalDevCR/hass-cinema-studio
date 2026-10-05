import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

async function load() {
  vi.resetModules();
  const { useToast } = await import("@/composables/useToast");
  return useToast();
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useToast", () => {
  it("pushes info toasts by default and exposes them reactively", async () => {
    const toast = await load();
    toast.push("Saved");
    expect(toast.toasts.value).toHaveLength(1);
    expect(toast.toasts.value[0]).toMatchObject({ message: "Saved", kind: "info" });
  });

  it("auto-dismisses, keeping errors on screen longer", async () => {
    const toast = await load();
    toast.push("Done", "success");
    toast.push("Broke", "error");
    await vi.advanceTimersByTimeAsync(4_000);
    expect(toast.toasts.value.map((t) => t.message)).toEqual(["Broke"]);
    await vi.advanceTimersByTimeAsync(4_000);
    expect(toast.toasts.value).toHaveLength(0);
  });

  it("dismisses on demand", async () => {
    const toast = await load();
    toast.push("One");
    toast.push("Two");
    toast.dismiss(toast.toasts.value[0]!.id);
    expect(toast.toasts.value.map((t) => t.message)).toEqual(["Two"]);
  });

  it("keeps at most four toasts", async () => {
    const toast = await load();
    for (let i = 0; i < 6; i++) toast.push(`m${i}`);
    expect(toast.toasts.value.map((t) => t.message)).toEqual(["m2", "m3", "m4", "m5"]);
  });
});
