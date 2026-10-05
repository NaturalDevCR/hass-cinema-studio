import { afterEach, expect, it, vi } from "vitest";
import { copyText } from "./clipboard";
afterEach(() => vi.restoreAllMocks());
it("uses Clipboard API when available", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.spyOn(navigator, "clipboard", "get").mockReturnValue({ writeText } as never);
  expect(await copyText("secret")).toBe(true);
  expect(writeText).toHaveBeenCalledWith("secret");
});
it.each(["unavailable", "rejected"])(
  "falls back to a selected hidden textarea when clipboard is %s",
  async (kind) => {
    vi.spyOn(navigator, "clipboard", "get").mockReturnValue(
      kind === "unavailable"
        ? (undefined as never)
        : ({ writeText: vi.fn().mockRejectedValue(new Error("denied")) } as never),
    );
    const focused = document.createElement("button");
    document.body.append(focused);
    focused.focus();
    const exec = vi.fn(() => {
      const textarea = document.querySelector("textarea")!;
      expect(textarea.value).toBe("secret");
      expect(textarea.selectionEnd).toBe(6);
      return true;
    });
    Object.defineProperty(document, "execCommand", { configurable: true, value: exec });
    expect(await copyText("secret")).toBe(true);
    expect(exec).toHaveBeenCalledWith("copy");
    expect(document.querySelector("textarea")).toBeNull();
    expect(document.activeElement).toBe(focused);
    focused.remove();
  },
);
it("returns false when both copy mechanisms fail", async () => {
  vi.spyOn(navigator, "clipboard", "get").mockReturnValue(undefined as never);
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: () => {
      throw new Error("denied");
    },
  });
  expect(await copyText("secret")).toBe(false);
  expect(document.querySelector("textarea")).toBeNull();
});
