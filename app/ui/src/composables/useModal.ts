import { onBeforeUnmount, onMounted, watch, type Ref } from "vue";

/**
 * Behaviour shared by every modal surface (Sheet, ConfirmDialog): scroll lock,
 * focus trap, Escape, inert background and focus restore. Modals stack: only the
 * top-most one reacts to the keyboard, and the page stays locked until the last
 * one closes.
 */

type Entry = { container: Ref<HTMLElement | null>; onEscape: () => void };

const stack: Entry[] = [];
let lockDepth = 0;
let savedOverflow = "";
let savedPaddingRight = "";

const FOCUSABLE = [
  "a[href]",
  "area[href]",
  "button",
  "input:not([type='hidden'])",
  "select",
  "textarea",
  "summary",
  "audio[controls]",
  "video[controls]",
  "[contenteditable]:not([contenteditable='false'])",
  "[tabindex]",
].join(",");

function isFocusable(el: HTMLElement): boolean {
  if (el.hasAttribute("disabled") || el.closest("[hidden],[inert]")) return false;
  const tabindex = el.getAttribute("tabindex");
  if (tabindex !== null && Number(tabindex) < 0) return false;
  return el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
}

export function focusableWithin(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(isFocusable);
}

function lockScroll(): void {
  if (lockDepth++ > 0) return;
  const { body, documentElement } = document;
  savedOverflow = body.style.overflow;
  savedPaddingRight = body.style.paddingRight;
  const scrollbar = window.innerWidth - documentElement.clientWidth;
  body.style.overflow = "hidden";
  if (scrollbar > 0) body.style.paddingRight = `${scrollbar}px`; // keep the layout from jumping
}

function unlockScroll(): void {
  if (lockDepth === 0 || --lockDepth > 0) return;
  document.body.style.overflow = savedOverflow;
  document.body.style.paddingRight = savedPaddingRight;
}

/** Everything outside the teleported modal layer becomes unreachable for keyboard and screen readers. */
function setBackgroundInert(inert: boolean): void {
  const root = document.getElementById("app");
  if (!root) return;
  if (inert) root.setAttribute("inert", "");
  else root.removeAttribute("inert");
}

function onKeydown(event: KeyboardEvent): void {
  const top = stack.at(-1);
  if (!top || event.isComposing) return;
  if (event.key === "Escape") {
    event.preventDefault();
    top.onEscape();
    return;
  }
  if (event.key !== "Tab") return;
  const container = top.container.value;
  if (!container) return;
  const items = focusableWithin(container);
  if (!items.length) {
    event.preventDefault();
    container.focus();
    return;
  }
  const first = items[0] as HTMLElement;
  const last = items[items.length - 1] as HTMLElement;
  const active = document.activeElement;
  const inside = active !== null && container.contains(active) && active !== container;
  if (event.shiftKey && (!inside || active === first)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (!inside || active === last)) {
    event.preventDefault();
    first.focus();
  }
}

export function useModal(
  open: Readonly<Ref<boolean>>,
  container: Ref<HTMLElement | null>,
  options: { onEscape: () => void; initialFocus?: () => HTMLElement | null | undefined },
): void {
  const entry: Entry = { container, onEscape: options.onEscape };
  let active = false;
  let returnTo: HTMLElement | null = null;

  function activate(): void {
    if (active) return;
    active = true;
    returnTo = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (stack.length === 0) document.addEventListener("keydown", onKeydown);
    stack.push(entry);
    lockScroll();
    setBackgroundInert(true);
    const target = options.initialFocus?.() ?? container.value;
    target?.focus({ preventScroll: true });
  }

  function deactivate(): void {
    if (!active) return;
    active = false;
    const index = stack.indexOf(entry);
    if (index >= 0) stack.splice(index, 1);
    unlockScroll();
    if (stack.length === 0) {
      document.removeEventListener("keydown", onKeydown);
      setBackgroundInert(false);
    }
    if (returnTo?.isConnected) returnTo.focus({ preventScroll: true });
    returnTo = null;
  }

  onMounted(() => {
    if (open.value) activate();
  });
  watch(
    open,
    (isOpen) => (isOpen ? activate() : deactivate()),
    { flush: "post" },
  );
  onBeforeUnmount(deactivate);
}
