import { ref } from "vue";
import { translate } from "@/i18n";
import { useToast } from "./useToast";

const currentId = ref<string | null>(null);
const playing = ref(false);
let video: HTMLVideoElement | null = null;

function reset(): void {
  currentId.value = null;
  playing.value = false;
}

/**
 * The one video element behind every inline card preview. Starting a clip always silences the
 * previous one, and the element is sound-on: playback only ever starts from a tap, never
 * as muted autoplay. It covers the card's preview area and shows native controls.
 */
function element(): HTMLVideoElement {
  if (!video) {
    video = document.createElement("video");
    video.preload = "none";
    video.muted = false;
    video.autoplay = false;
    // Native controls give seeking, volume and fullscreen; the card overlays the element.
    video.controls = true;
    video.playsInline = true;
    video.className = "absolute inset-0 size-full bg-black object-contain";
    video.addEventListener("ended", reset);
    // Native controls can resume playback without going through toggle().
    video.addEventListener("play", () => {
      if (currentId.value) playing.value = true;
    });
    // External pauses (media keys, an incoming call). Ignore the late event our own
    // pause() queues when we switch clips: by then play() has made `paused` false again.
    video.addEventListener("pause", () => {
      if (video?.paused) playing.value = false;
    });
    video.addEventListener("error", () => {
      if (!currentId.value) return;
      reset();
      useToast().push(translate("player.error"), "error");
    });
  }
  return video;
}

function stop(): void {
  if (video) {
    video.pause();
    video.currentTime = 0;
    // Dropping the source (and reloading) cancels any pending network buffering.
    video.removeAttribute("src");
    video.load();
    video.remove();
  }
  reset();
}

/**
 * Plays `url` for clip `id`. Calling it again for the clip that is playing pauses it in place;
 * calling it for the clip that is current but paused resumes it from where it stopped. `host` is
 * the element the video should be shown in (the card that asked); omit it to keep the video
 * wherever it already is.
 */
function toggle(id: string, url: string, host?: HTMLElement): void {
  const el = element();
  if (currentId.value === id) {
    if (host && el.parentElement !== host) host.appendChild(el);
    if (playing.value) {
      el.pause();
      playing.value = false;
      return;
    }
    // Paused (by us or externally): resume without touching src, so position and buffer survive.
    playing.value = true;
    play(el, id);
    return;
  }
  el.pause();
  if (host && el.parentElement !== host) host.appendChild(el);
  el.src = url;
  el.currentTime = 0;
  currentId.value = id;
  playing.value = true;
  play(el, id);
}

function play(el: HTMLVideoElement, id: string): void {
  el.play().catch(() => {
    if (currentId.value !== id) return; // superseded by another clip meanwhile
    reset();
    useToast().push(translate("player.error"), "error");
  });
}

export function usePlayer() {
  return { currentId, playing, toggle, stop, element };
}
