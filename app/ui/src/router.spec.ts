import { createMemoryHistory, type RouteLocationNormalized } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAppRouter } from "@/router";

async function go(path: string) {
  const router = createAppRouter(createMemoryHistory());
  await router.push(path);
  return router.currentRoute.value;
}

describe("router", () => {
  it("serves the four top level views", async () => {
    expect((await go("/")).name).toBe("library");
    expect((await go("/upload")).name).toBe("upload");
    expect((await go("/organize")).name).toBe("organize");
    expect((await go("/system")).name).toBe("system");
  });

  it("nests the clip editor under Library so it stays mounted", async () => {
    const route = await go("/clips/abc123");
    expect(route.name).toBe("clip");
    expect(route.params.id).toBe("abc123");
    expect(route.matched.map((r) => r.name)).toEqual(["library", "clip"]);
  });

  it("falls back to Library for unknown paths", async () => {
    expect((await go("/nope/at/all")).name).toBe("library");
  });

  it("gives each top level route a title key", async () => {
    expect((await go("/system")).matched[0]?.meta.titleKey).toBe("nav.system");
    expect((await go("/clips/x")).matched[0]?.meta.titleKey).toBe("nav.library");
  });
});

describe("scrollBehavior", () => {
  const router = createAppRouter(createMemoryHistory());
  const location = (path: string) => router.resolve(path) as unknown as RouteLocationNormalized;
  const scroll = (to: string, from: string) =>
    router.options.scrollBehavior!(location(to), location(from), null);
  const stubMotion = (reduce: boolean) =>
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: reduce && query.includes("reduced-motion") }));
  afterEach(() => vi.unstubAllGlobals());

  it("scrolls to anchors smoothly by default", async () => {
    stubMotion(false);
    expect(await scroll("/organize#seasons", "/")).toEqual({ el: "#seasons", behavior: "smooth" });
  });

  it("jumps instead of animating when the user prefers reduced motion", async () => {
    stubMotion(true);
    expect(await scroll("/organize#seasons", "/")).toEqual({ el: "#seasons", behavior: "auto" });
  });

  it("lets System scroll Import after its panels have loaded", async () => {
    expect(await scroll("/system?section=import", "/")).toBe(false);
    expect(await scroll("/system#import", "/")).toBe(false);
  });

  it("keeps Library's scroll when the editor opens, closes or the query changes", async () => {
    expect(await scroll("/clips/a", "/")).toBe(false);
    expect(await scroll("/", "/clips/a")).toBe(false);
    expect(await scroll("/?c=doors", "/")).toBe(false);
    expect(await scroll("/upload", "/")).toEqual({ top: 0 });
  });
});
