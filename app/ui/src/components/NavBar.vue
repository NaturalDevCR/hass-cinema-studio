<script setup lang="ts">
import { useRoute } from "vue-router";
import { mdiCog, mdiFilmstripBox, mdiShapeOutline, mdiUpload } from "@mdi/js";
import Icon from "@/components/Icon.vue";
import LocaleSwitch from "@/components/LocaleSwitch.vue";
import type { MessageKey } from "@/i18n";
import { useI18n } from "@/i18n";

const { t } = useI18n();
const route = useRoute();

const items: { name: string; path: string; label: MessageKey; icon: string }[] = [
  { name: "library", path: "/", label: "nav.library", icon: mdiFilmstripBox },
  { name: "upload", path: "/upload", label: "nav.upload", icon: mdiUpload },
  { name: "organize", path: "/organize", label: "nav.organize", icon: mdiShapeOutline },
  { name: "system", path: "/system", label: "nav.system", icon: mdiCog },
];

// Library owns "/" and the clip editor nested under it, so it matches exactly or by its child
// record; every other section matches itself and anything below it.
function active(item: { name: string; path: string }): boolean {
  if (item.path === "/") return route.path === "/" || route.matched.some((r) => r.name === "library");
  return route.path === item.path || route.path.startsWith(`${item.path}/`);
}
</script>

<template>
  <!-- One landmark, two layouts: fixed bottom tab bar below md, sticky sidebar from md up. -->
  <nav
    :aria-label="t('nav.label')"
    class="fixed inset-x-0 bottom-0 z-40 flex flex-col border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:sticky md:inset-x-auto md:top-0 md:bottom-auto md:h-dvh md:w-60 md:shrink-0 md:border-t-0 md:border-r md:bg-surface md:p-3 md:pb-3 md:backdrop-blur-none"
  >
    <div class="hidden items-center gap-3 px-3 pt-3 pb-5 md:flex">
      <span class="grid size-9 place-items-center rounded-lg bg-accent-strong text-accent-ink">
        <Icon :path="mdiFilmstripBox" :size="22" />
      </span>
      <span class="text-base font-semibold tracking-tight">{{ t("app.name") }}</span>
    </div>

    <ul class="flex w-full md:flex-col md:gap-1">
      <li v-for="item in items" :key="item.name" class="min-w-0 flex-1 md:flex-none">
        <RouterLink :to="{ name: item.name }" custom v-slot="{ href, navigate }">
          <a
            :href="href"
            :aria-current="active(item) ? 'page' : undefined"
            class="flex min-h-14 w-full flex-col items-center justify-center gap-0.5 rounded-lg px-2 text-xs font-medium transition-colors hover:text-ink md:min-h-11 md:flex-row md:justify-start md:gap-3 md:px-3 md:text-sm"
            :class="active(item) ? 'text-ink md:bg-raised' : 'text-muted md:hover:bg-hover'"
            @click="navigate"
          >
            <span
              class="grid place-items-center rounded-full px-4 py-1 transition-colors md:bg-transparent! md:p-0"
                :class="active(item) ? 'bg-accent-soft text-accent' : ''"
            >
              <Icon :path="item.icon" :size="22" />
            </span>
            <span class="truncate">{{ t(item.label) }}</span>
          </a>
        </RouterLink>
      </li>
    </ul>

    <div class="mt-auto hidden px-1 pb-1 md:block">
      <LocaleSwitch />
    </div>
  </nav>
</template>
