import { afterEach, describe, expect, it, vi } from "vitest";
import { newId } from "./id";

describe("newId", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses crypto.randomUUID when available", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "uuid-1" });
    expect(newId("target")).toBe("target-uuid-1");
  });

  it("falls back to unique ids when randomUUID is unavailable (plain HTTP)", () => {
    vi.stubGlobal("crypto", { randomUUID: undefined });
    const ids = Array.from({ length: 50 }, () => newId("target"));
    expect(new Set(ids).size).toBe(50);
    expect(ids.every((id) => id.startsWith("target-"))).toBe(true);
  });

  it("falls back when crypto itself is missing", () => {
    vi.stubGlobal("crypto", undefined);
    expect(newId("x")).toMatch(/^x-/);
  });
});
