import { createRouter, createWebHashHistory, type RouteLocationNormalized, type RouterHistory } from "vue-router";
import type { MessageKey } from "@/i18n";

declare module "vue-router" {
  interface RouteMeta {
    /** i18n key for the header title and document title. Set on top-level records only. */
    titleKey?: MessageKey;
  }
}

const prefersReducedMotion = () =>
  typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const isEditor = (route: RouteLocationNormalized) => route.name === "clip";

/**
 * Hash history: the Ingress prefix is unknown at build time, and history mode would
 * 404 on reload behind it. The clip editor is a child of Library so Library stays
 * mounted underneath the editor sheet.
 */
export function createAppRouter(history: RouterHistory = createWebHashHistory()) {
  return createRouter({
    history,
    routes: [
      {
        path: "/",
        name: "library",
        component: () => import("@/views/LibraryView.vue"),
        meta: { titleKey: "nav.library" },
        children: [
          {
            path: "clips/:id",
            name: "clip",
            component: () => import("@/views/ClipEditorView.vue"),
            props: true,
          },
        ],
      },
      {
        path: "/upload",
        name: "upload",
        component: () => import("@/views/UploadView.vue"),
        meta: { titleKey: "nav.upload" },
      },
      {
        path: "/organize",
        name: "organize",
        component: () => import("@/views/OrganizeView.vue"),
        meta: { titleKey: "nav.organize" },
      },
      {
        path: "/system",
        name: "system",
        component: () => import("@/views/SystemView.vue"),
        meta: { titleKey: "nav.system" },
      },
      { path: "/:pathMatch(.*)*", redirect: { name: "library", params: {} } },
    ],
    scrollBehavior(to, from, saved) {
      if (saved) return saved;
      // System owns this scroll: its target is rendered only after state loads.
      if (to.name === "system" && (to.query.section === "import" || to.hash === "#import")) return false;
      if (to.hash) return { el: to.hash, behavior: prefersReducedMotion() ? "auto" : "smooth" };
      // Opening or closing the editor sheet, or changing filters in the query, must not
      // throw the Library scroll position away.
      if (to.path === from.path) return false;
      if ((isEditor(to) || isEditor(from)) && to.matched[0] === from.matched[0]) return false;
      return { top: 0 };
    },
  });
}

export const router = createAppRouter();
