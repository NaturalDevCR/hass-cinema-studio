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
 * as muted autoplay.
 */
function element(): HTMLVideoElement {
  if (!video) {
    video = document.createElement("video");
    video.preload = "none";
    video.muted = false;
    video.autoplay = false;
    video.controls = false;
    video.playsInline = true;
    video.addEventListener("ended", reset);
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
    video.remove();
  }
  reset();
}

/**
 * Plays `url` for clip `id`; calling it again for the clip that is playing stops it. `host` is
 * the element the video should be shown in (the card that asked); omit it to keep the video
 * wherever it already is.
 */
function toggle(id: string, url: string, host?: HTMLElement): void {
  if (currentId.value === id && playing.value) {
    stop();
    return;
  }
  const el = element();
  el.pause();
  if (host && el.parentElement !== host) host.appendChild(el);
  el.src = url;
  el.currentTime = 0;
  currentId.value = id;
  playing.value = true;
  el.play().catch(() => {
    if (currentId.value !== id) return; // superseded by another clip meanwhile
    reset();
    useToast().push(translate("player.error"), "error");
  });
}

export function usePlayer() {
  return { currentId, playing, toggle, stop, element };
}
