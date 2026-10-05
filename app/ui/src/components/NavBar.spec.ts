import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { beforeEach, describe, expect, it } from "vitest";
import NavBar from "@/components/NavBar.vue";
import { useI18n } from "@/i18n";
import { createAppRouter } from "@/router";

async function mountNav(path = "/") {
  const router = createAppRouter(createMemoryHistory());
  await router.push(path);
  await router.isReady();
  const wrapper = mount(NavBar, { global: { plugins: [router] } });
  return { wrapper, router };
}

beforeEach(() => useI18n().setLocale("en"));

describe("NavBar", () => {
  it("renders the four sections as links in order", async () => {
    const { wrapper } = await mountNav();
    const links = wrapper.findAll("a");
    expect(links.map((l) => l.text())).toEqual(["Library", "Upload", "Organize", "System"]);
    expect(links.map((l) => l.attributes("href"))).toEqual(["/", "/upload", "/organize", "/system"]);
    expect(wrapper.get("nav").attributes("aria-label")).toBe("Main navigation");
  });

  it("shows the Cinema Studio logo text and one icon per section", async () => {
    const { wrapper } = await mountNav();
    expect(wrapper.text()).toContain("Cinema Studio");
    expect(wrapper.findAll("li svg")).toHaveLength(4);
  });

  it("marks the current section", async () => {
    const { wrapper } = await mountNav("/upload");
    const current = wrapper.findAll('a[aria-current="page"]');
    expect(current.map((l) => l.text())).toEqual(["Upload"]);
  });

  it("keeps Library marked while the clip editor is open on top of it", async () => {
    const { wrapper } = await mountNav("/clips/abc");
    expect(wrapper.findAll('a[aria-current="page"]').map((l) => l.text())).toEqual(["Library"]);
  });

  it("switches language", async () => {
    const { wrapper } = await mountNav();
    const spanish = wrapper.findAll("button").find((b) => b.attributes("lang") === "es")!;
    await spanish.trigger("click");
    await flushPromises();
    expect(wrapper.findAll("a").map((l) => l.text())).toEqual(["Biblioteca", "Subir", "Organizar", "Sistema"]);
    expect(spanish.attributes("aria-pressed")).toBe("true");
  });
});
