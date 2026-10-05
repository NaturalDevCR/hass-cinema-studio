import { mdiFilm, mdiMovieOpen } from "@mdi/js";
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it } from "vitest";
import EmptyState from "@/components/EmptyState.vue";
import Icon from "@/components/Icon.vue";
import SeasonBadge from "@/components/SeasonBadge.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useI18n } from "@/i18n";

beforeEach(() => useI18n().setLocale("en"));

describe("Icon", () => {
  it("is decorative unless labelled", () => {
    const svg = mount(Icon, { props: { path: mdiFilm } }).get("svg");
    expect(svg.attributes("aria-hidden")).toBe("true");
    expect(svg.attributes("role")).toBeUndefined();
    expect(svg.get("path").attributes("d")).toBe(mdiFilm);
    expect(svg.attributes("viewBox")).toBe("0 0 24 24");
  });

  it("exposes a label to assistive tech and honours size", () => {
    const svg = mount(Icon, { props: { path: mdiFilm, label: "Door", size: 32 } }).get("svg");
    expect(svg.attributes("role")).toBe("img");
    expect(svg.attributes("aria-label")).toBe("Door");
    expect(svg.attributes("aria-hidden")).toBeUndefined();
    expect(svg.attributes("width")).toBe("32");
    expect(svg.attributes("height")).toBe("32");
  });
});

describe("StatusPill", () => {
  it.each([
    ["processing", "Processing"],
    ["ready", "Ready"],
    ["rendering", "Rendering"],
    ["failed", "Failed"],
  ] as const)("labels %s", (status, label) => {
    const wrapper = mount(StatusPill, { props: { status } });
    expect(wrapper.text()).toBe(label);
    expect(wrapper.attributes("data-status")).toBe(status);
  });

  it("localizes", () => {
    useI18n().setLocale("es");
    expect(mount(StatusPill, { props: { status: "ready" } }).text()).toBe("Listo");
  });
});

describe("SeasonBadge", () => {
  const season = { name: "Halloween", color: "#f97316", icon: "mdi:film" };

  it("shows the name with the mapped icon and tint", () => {
    const wrapper = mount(SeasonBadge, { props: { season } });
    expect(wrapper.text()).toBe("Halloween");
    expect(wrapper.get("path").attributes("d")).toBe(mdiFilm);
    expect(wrapper.attributes("style")).toContain("#f97316");
  });

  it("falls back to the generic movie icon for unknown icons", () => {
    const wrapper = mount(SeasonBadge, { props: { season: { ...season, icon: "mdi:nope" } } });
    expect(wrapper.get("path").attributes("d")).toBe(mdiMovieOpen);
  });

  it("can hide the label while keeping it accessible", () => {
    const wrapper = mount(SeasonBadge, { props: { season, compact: true } });
    expect(wrapper.get(".sr-only").text()).toBe("Halloween");
  });
});

describe("EmptyState", () => {
  it("renders title, description and actions", () => {
    const wrapper = mount(EmptyState, {
      props: { title: "Nothing here", description: "Upload something.", icon: mdiMovieOpen },
      slots: { default: '<button class="go">Go</button>' },
    });
    expect(wrapper.get("h3").text()).toBe("Nothing here");
    expect(wrapper.text()).toContain("Upload something.");
    expect(wrapper.find("button.go").exists()).toBe(true);
    expect(wrapper.find("svg").attributes("aria-hidden")).toBe("true");
  });
});
