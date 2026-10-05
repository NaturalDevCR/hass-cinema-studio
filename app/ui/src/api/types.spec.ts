import { expectTypeOf, it } from "vitest";
import type { CollectionPatch, SeasonInput } from "./types";

it("excludes collection ordering from PATCH input", () => {
  expectTypeOf<"sort_order">().not.toMatchTypeOf<keyof CollectionPatch>();
  expectTypeOf<"order">().not.toMatchTypeOf<keyof CollectionPatch>();
});

it("requires non-null dates and a collection when creating a season", () => {
  expectTypeOf<SeasonInput["start"]>().toEqualTypeOf<string>();
  expectTypeOf<SeasonInput["end"]>().toEqualTypeOf<string>();
  expectTypeOf<SeasonInput["collection_id"]>().toEqualTypeOf<string>();
});
