vi.mock("@/composables/useStudio", async (original) => {
  const actual = await original<typeof import("@/composables/useStudio")>();
  const refresh = vi.fn().mockResolvedValue(undefined),
    refreshClips = vi.fn().mockResolvedValue(undefined);
  return {
    ...actual,
    useStudio: () => ({ ...actual.useStudio(), refresh, refreshClips }),
  };
});
import { mount, flushPromises } from "@vue/test-utils";
import { beforeEach, it, expect, vi } from "vitest";
import SeasonForm from "./SeasonForm.vue";
import { ui } from "@/api/client";
import { useStudio } from "@/composables/useStudio";
import { makeCollection, makeSeason } from "@/test/factories";

const collections = [makeCollection({ id: "regular", name: "Regular" }), makeCollection({ id: "horror", name: "Horror" })];
beforeEach(() => {
  useStudio().collections.value = collections;
});
it("validates name and priority; month selects adapt including leap day", async () => {
  const create = vi.spyOn(ui.seasons, "create").mockResolvedValue(makeSeason({ id: "new" }));
  const w = mount(SeasonForm);
  await w.get("form").trigger("submit");
  expect(create).not.toHaveBeenCalled();
  await w.get('[data-test="name"]').setValue("Winter");
  await w.get('[data-test="start-day"]').setValue("31");
  await w.get('[data-test="start-month"]').setValue("2");
  expect((w.get('[data-test="start-day"]').element as HTMLSelectElement).value).toBe("29");
  expect(w.get('[data-test="start-day"]').findAll("option")).toHaveLength(29);
  await w.get('[data-test="start-day"]').setValue("29");
  await w.get('[data-test="start-month"]').setValue("4");
  expect(w.get('[data-test="start-day"]').findAll("option")).toHaveLength(30);
  await w.get('[data-test="priority"]').setValue("1001");
  await w.get("form").trigger("submit");
  expect(create).not.toHaveBeenCalled();
  await w.get('[data-test="priority"]').setValue("10");
  await w.get('[data-test="collection"]').setValue("horror");
  await w.get("form").trigger("submit");
  await flushPromises();
  expect(create).toHaveBeenCalledExactlyOnceWith({
    name: "Winter", color: "#34d399", icon: "mdi:calendar-star",
    start: "04-29", end: "12-31", priority: 10, collection_id: "horror",
  });
  create.mockRestore();
});
it("offers every collection and defaults to the first", () => {
  const w = mount(SeasonForm);
  const select = w.get('[data-test="collection"]');
  expect(select.findAll("option").map((o) => o.text())).toEqual(["Regular", "Horror"]);
  expect((select.element as HTMLSelectElement).value).toBe("regular");
});
it("keeps the collection of an existing season when patching it", async () => {
  const update = vi.spyOn(ui.seasons, "update").mockResolvedValue(makeSeason({ id: "oct" }));
  const w = mount(SeasonForm, {
    props: { season: makeSeason({ id: "oct", name: "Oct", start: "10-01", end: "10-31", collection_id: "horror" }) },
  });
  await w.get("form").trigger("submit");
  await flushPromises();
  expect(update).toHaveBeenCalledWith("oct", expect.objectContaining({ collection_id: "horror" }));
  update.mockRestore();
});
it("requires a collection when none exists yet", async () => {
  useStudio().collections.value = [];
  const create = vi.spyOn(ui.seasons, "create");
  const w = mount(SeasonForm);
  await w.get('[data-test="name"]').setValue("Winter");
  await w.get("form").trigger("submit");
  expect(create).not.toHaveBeenCalled();
  expect(w.get('[role="alert"]').text()).toBe("Choose the collection this season plays.");
  create.mockRestore();
});
it("only patches name, color and icon for regular", async () => {
  const update = vi.spyOn(ui.seasons, "update").mockResolvedValue(makeSeason({ id: "regular" }));
  const w = mount(SeasonForm, {
    props: {
      season: makeSeason({ id: "regular", name: "Regular", builtin: true }),
    },
  });
  expect(w.find('[data-test="priority"]').exists()).toBe(false);
  await w.get("form").trigger("submit");
  await flushPromises();
  expect(update).toHaveBeenCalledWith("regular", {
    name: "Regular",
    color: "#34d399",
    icon: "mdi:calendar-blank",
  });
  update.mockRestore();
});
