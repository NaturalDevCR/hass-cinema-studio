import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi } from "vitest";
import SeasonTimeline from "./SeasonTimeline.vue";
import { makeSeason } from "@/test/factories";
import { ui } from "@/api/client";
describe("SeasonTimeline", () => {
  it("draws wrap-around ranges as two segments and October as one; regular is excluded", () => {
    const w = mount(SeasonTimeline, {
      props: {
        seasons: [
          makeSeason({ id: "winter", start: "12-01", end: "01-06" }),
          makeSeason({ id: "oct", start: "10-01", end: "10-31" }),
          makeSeason({ id: "regular" }),
        ],
      },
    });
    expect(w.findAll('[data-season="winter"]')).toHaveLength(2);
    expect(w.findAll('[data-season="oct"]')).toHaveLength(1);
    expect(w.findAll('[data-season="regular"]')).toHaveLength(0);
    expect(w.get('[data-season="winter"]').attributes("aria-label")).toContain("12-01");
    expect(w.findAll('[data-test="month"]')).toHaveLength(12);
    expect(w.find('[data-test="today"]').exists()).toBe(true);
  });
  it("resolves a date using the API and shows the returned season", async () => {
    const resolve = vi.spyOn(ui.seasons, "resolve").mockResolvedValue({ date: "2026-10-31", season_id: "oct", collection_id: "regular" });
    const w = mount(SeasonTimeline, {
      props: {
        seasons: [
          makeSeason({
            id: "oct",
            name: "Halloween",
            start: "10-01",
            end: "10-31",
          }),
        ],
      },
    });
    await w.get('input[type="date"]').setValue("2026-10-31");
    await flushPromises();
    expect(resolve).toHaveBeenCalledWith("2026-10-31");
    expect(w.text()).toContain("Halloween");
    resolve.mockRestore();
  });
});
it("ignores stale date results and presents resolve errors inline", async () => {
  let finish!: (value: { date: string; season_id: string; collection_id: string }) => void;
  const resolve = vi
    .spyOn(ui.seasons, "resolve")
    .mockImplementationOnce(
      () =>
        new Promise((r) => {
          finish = r;
        }),
    )
    .mockRejectedValueOnce(new Error("date unavailable"));
  const w = mount(SeasonTimeline, {
    props: { seasons: [makeSeason({ id: "old", name: "Old result" })] },
  });
  await w.get('input[type="date"]').setValue("2026-01-01");
  await w.get('input[type="date"]').setValue("2026-02-01");
  await flushPromises();
  finish({ date: "2026-01-01", season_id: "old", collection_id: "regular" });
  await flushPromises();
  expect(w.get('[role="alert"]').text()).toBe("date unavailable");
  expect(w.text()).not.toContain("Old result");
  resolve.mockRestore();
});

it.each([
  ["10-01", "10-31", [[274, 31]]],
  ["12-01", "01-06", [[335, 31], [0, 6]]],
  ["02-29", "02-29", [[59, 1]]],
])("uses inclusive leap-year geometry for %s through %s", (start, end, geometry) => {
  const w = mount(SeasonTimeline, { props: { seasons: [makeSeason({ id: "range", start, end })] } });
  const segments = w.findAll('[data-season="range"]');
  expect(segments).toHaveLength(geometry.length);
  segments.forEach((segment, i) => {
    const style = (segment.element as HTMLElement).style;
    const [left, width] = geometry[i]!;
    expect(parseFloat(style.left)).toBeCloseTo(left! / 366 * 100);
    expect(parseFloat(style.width)).toBeCloseTo(width! / 366 * 100);
    expect(segment.classes()).toContain("min-w-[4px]");
    expect(segment.attributes("aria-hidden")).toBe(i > 0 ? "true" : undefined);
  });
});
it("can hide the timeline legend when the organize list supplies it", () => {
  const w = mount(SeasonTimeline, { props: { seasons: [makeSeason({ id: "one", start: "01-01", end: "01-01" })], showLegend: false } });
  expect(w.find("ul").exists()).toBe(false);
});
