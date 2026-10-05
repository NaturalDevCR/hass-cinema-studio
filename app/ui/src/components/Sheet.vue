<script setup lang="ts">
import { ref, toRef, useId } from "vue";
import { mdiClose } from "@mdi/js";
import Icon from "@/components/Icon.vue";
import { useModal } from "@/composables/useModal";
import { useI18n } from "@/i18n";

// Full-screen on phones, right-hand drawer (max-w-2xl) from md up. The parent owns
// `open`; Escape, the close button and the backdrop all just emit `close` so the
// parent can run an unsaved-changes guard first.
const props = defineProps<{ open: boolean; title: string; wide?: boolean }>();
const emit = defineEmits<{ close: [] }>();

const { t } = useI18n();
const panel = ref<HTMLElement | null>(null);
const titleId = useId();

useModal(toRef(props, "open"), panel, { onEscape: () => emit("close") });
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet" appear>
      <div v-if="open" class="sheet-root fixed inset-0 z-50">
        <div data-test="backdrop" class="absolute inset-0 bg-black/60" aria-hidden="true" @click="emit('close')" />
        <div
          ref="panel"
          role="dialog"
          aria-modal="true"
          tabindex="-1"
          :aria-labelledby="titleId"
          class="sheet-panel absolute inset-0 flex flex-col bg-surface outline-none md:left-auto md:w-full md:border-l md:border-line md:shadow-2xl"
          :class="wide ? 'md:max-w-7xl' : 'md:max-w-2xl'"
        >
          <header
            class="flex shrink-0 items-center gap-2 border-b border-line py-2 pr-2 pl-4 pt-[max(0.5rem,env(safe-area-inset-top))]"
          >
            <h2 :id="titleId" class="min-w-0 flex-1 truncate text-base font-semibold">{{ title }}</h2>
            <slot name="meta" />
            <button
              type="button"
              class="btn-ghost size-11 shrink-0 p-0!"
              :aria-label="t('common.close')"
              @click="emit('close')"
            >
              <Icon :path="mdiClose" :size="22" />
            </button>
          </header>

          <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4">
            <slot />
          </div>

          <footer
            v-if="$slots.footer"
            class="shrink-0 border-t border-line bg-surface px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
          >
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
