import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { LegacyReport } from "@/api/types";
import LegacyImportPanel from "./LegacyImportPanel.vue";

const report: LegacyReport = {
  run_id: "run-1",
  started_at: "2026-01-01T00:00:00Z",
  finished_at: null,
  catalog_revision: 7,
  imported: ["a", "b"],
  queued_for_render: ["c"],
  needs_source: ["d"],
  skipped: [{ clip_id: "e", reason: "unchanged" }],
  missing_assets: ["intro.mp4", "outro.mp4", "intro.mp4"],
};

describe("LegacyImportPanel", () => {
  it("renders each count next to its label", () => {
    const wrapper = mount(LegacyImportPanel, { props: { report } });
    const pairs = wrapper.findAll("dl > div").map((row) => [row.get("dt").text(), row.get("dd").text()]);
    expect(pairs).toEqual([
      ["Imported", "2"],
      ["Queued for render", "1"],
      ["Needs source", "1"],
      ["Skipped", "1"],
      ["Missing assets", "3"],
    ]);
  });

  it("renders the list contents under each heading, tolerating duplicates", () => {
    const wrapper = mount(LegacyImportPanel, { props: { report } });
    const lists = wrapper.findAll("details").map((section) => [
      section.get("summary").text(),
      section.findAll("li").map((item) => item.text()),
    ]);
    expect(lists).toEqual([
      ["Imported", ["a", "b"]],
      ["Queued for render", ["c"]],
      ["Needs source", ["d"]],
      ["Skipped", ["e: unchanged"]],
      ["Missing assets", ["intro.mp4", "outro.mp4", "intro.mp4"]],
    ]);
  });

  it("shows the run id, a formatted timestamp and the action instruction", () => {
    const wrapper = mount(LegacyImportPanel, { props: { report } });
    const meta = wrapper.get("p.text-sm").text();
    expect(meta).toContain("run-1");
    expect(meta).not.toContain("2026-01-01T00:00:00Z");
    expect(wrapper.text()).toContain("Run the action cinema_studio.import_legacy from Home Assistant.");
  });

  it("shows the empty message without a report", () => {
    const wrapper = mount(LegacyImportPanel, { props: { report: null } });
    expect(wrapper.text()).toContain("No legacy import report yet.");
    expect(wrapper.find("dl").exists()).toBe(false);
  });
});
