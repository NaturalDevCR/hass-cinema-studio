import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { LegacyReport } from "@/api/types";
import LegacyImportPanel from "./LegacyImportPanel.vue";

describe("LegacyImportPanel", () => {
  it("renders counts from the last import report", () => {
    const report: LegacyReport = {
      run_id: "run-1", started_at: "2026-01-01T00:00:00Z", finished_at: null,
      catalog_revision: 7, imported: ["a", "b"], queued_for_render: ["c"], needs_source: ["d"],
      skipped: [{ clip_id: "e", reason: "unchanged" }], missing_assets: ["intro.mp4"],
    };
    const wrapper = mount(LegacyImportPanel, { props: { report } });
    expect(wrapper.text()).toContain("2");
    expect(wrapper.text()).toContain("1");
    expect(wrapper.text()).toContain("cinema_studio.import_legacy");
  });
});
