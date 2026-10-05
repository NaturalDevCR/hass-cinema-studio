import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import BulkBar from "./BulkBar.vue";

describe("BulkBar", () => {
  it("emits each supported bulk action", async () => {
    const wrapper = mount(BulkBar, { props: { count: 2, total: 4 } });
    for (const action of ["move", "enable", "disable", "normalize", "rerender", "delete"]) {
      await wrapper.get(`[data-test="action-${action}"]`).trigger("click");
    }
    expect(wrapper.emitted("action")?.map((event) => event[0])).toEqual(["move", "enable", "disable", "normalize", "rerender", "delete"]);
  });
});
