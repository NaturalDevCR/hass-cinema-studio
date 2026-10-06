import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let playImpl: () => Promise<void> = async () => undefined;
let play: ReturnType<typeof vi.spyOn>;
let pause: ReturnType<typeof vi.spyOn>;
let loadSpy: ReturnType<typeof vi.spyOn>;

async function load() {
  vi.resetModules();
  const { usePlayer } = await import("@/composables/usePlayer");
  const { useToast } = await import("@/composables/useToast");
  return { player: usePlayer(), toast: useToast() };
}

beforeEach(() => {
  playImpl = async () => undefined;
  play = vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => playImpl());
  pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  loadSpy = vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => undefined);
});
afterEach(() => vi.restoreAllMocks());

describe("usePlayer", () => {
  it("shares one HTMLVideoElement that is not muted and never autoplays", async () => {
    const { player } = await load();
    const video = player.element();
    expect(video).toBeInstanceOf(HTMLVideoElement);
    expect(player.element()).toBe(video);
    expect(video.muted).toBe(false);
    expect(video.autoplay).toBe(false);
    expect(video.preload).toBe("none");
    expect(video.controls).toBe(true);
    expect(video.playsInline).toBe(true);
    expect(play).not.toHaveBeenCalled();
  });

  it("plays a url and tracks the current clip", async () => {
    const { player } = await load();
    player.toggle("c1", "api/ui/clips/c1/render?v=1");
    expect(player.element().getAttribute("src")).toBe("api/ui/clips/c1/render?v=1");
    expect(play).toHaveBeenCalledTimes(1);
    expect(player.currentId.value).toBe("c1");
    expect(player.playing.value).toBe(true);
  });

  it("toggling the playing clip pauses it in place and keeps it selected", async () => {
    const { player } = await load();
    player.toggle("c1", "u1");
    const video = player.element();
    video.currentTime = 12;
    play.mockClear();
    player.toggle("c1", "u1");
    expect(pause).toHaveBeenCalled();
    expect(player.playing.value).toBe(false);
    expect(player.currentId.value).toBe("c1");
    expect(video.getAttribute("src")).toBe("u1");
    expect(video.currentTime).toBe(12);
    expect(loadSpy).not.toHaveBeenCalled();
  });

  it("toggling a paused clip resumes it without rewinding or reloading the source", async () => {
    const { player } = await load();
    player.toggle("c1", "u1");
    const video = player.element();
    video.currentTime = 12;
    player.toggle("c1", "u1"); // pause
    play.mockClear();
    player.toggle("c1", "u1"); // resume
    expect(play).toHaveBeenCalledTimes(1);
    expect(player.playing.value).toBe(true);
    expect(player.currentId.value).toBe("c1");
    expect(video.getAttribute("src")).toBe("u1");
    expect(video.currentTime).toBe(12);
  });

  it("resumes after an external pause too", async () => {
    const { player } = await load();
    player.toggle("c1", "u1");
    player.element().dispatchEvent(new Event("pause"));
    play.mockClear();
    player.toggle("c1", "u1");
    expect(play).toHaveBeenCalledTimes(1);
    expect(player.playing.value).toBe(true);
  });

  it("switches sources on the same element, silencing the previous clip", async () => {
    const { player } = await load();
    player.toggle("c1", "u1");
    const video = player.element();
    player.toggle("c2", "u2");
    expect(player.element()).toBe(video);
    expect(video.getAttribute("src")).toBe("u2");
    expect(play).toHaveBeenCalledTimes(2);
    expect(player.currentId.value).toBe("c2");
    expect(player.playing.value).toBe(true);
  });

  it("moves the element into the host a card hands over", async () => {
    const { player } = await load();
    const a = document.createElement("div");
    const b = document.createElement("div");
    player.toggle("c1", "u1", a);
    expect(a.contains(player.element())).toBe(true);
    player.toggle("c2", "u2", b);
    expect(a.contains(player.element())).toBe(false);
    expect(b.contains(player.element())).toBe(true);
  });

  it("resets when playback ends", async () => {
    const { player } = await load();
    player.toggle("c1", "u1");
    player.element().dispatchEvent(new Event("ended"));
    expect(player.playing.value).toBe(false);
    expect(player.currentId.value).toBeNull();
  });

  it("follows an external pause but keeps the clip selected", async () => {
    const { player } = await load();
    player.toggle("c1", "u1");
    player.element().dispatchEvent(new Event("pause"));
    expect(player.playing.value).toBe(false);
    expect(player.currentId.value).toBe("c1");
  });

  it("stop() pauses, rewinds, drops the source, detaches the element and clears state", async () => {
    const { player } = await load();
    const host = document.createElement("div");
    player.toggle("c1", "u1", host);
    player.stop();
    expect(pause).toHaveBeenCalled();
    expect(player.element().hasAttribute("src")).toBe(false);
    expect(loadSpy).toHaveBeenCalledTimes(1);
    expect(player.element().currentTime).toBe(0);
    expect(player.currentId.value).toBeNull();
    expect(player.playing.value).toBe(false);
    expect(host.contains(player.element())).toBe(false);
  });

  it("reports playback failures with a toast and resets", async () => {
    const { player, toast } = await load();
    playImpl = () => Promise.reject(new Error("NotSupportedError"));
    player.toggle("c1", "u1");
    await Promise.resolve();
    await Promise.resolve();
    expect(player.playing.value).toBe(false);
    expect(player.currentId.value).toBeNull();
    expect(toast.toasts.value.at(-1)?.kind).toBe("error");
  });

  it("ignores a late failure from a clip that was superseded", async () => {
    const { player, toast } = await load();
    let fail!: (reason: unknown) => void;
    playImpl = () => new Promise<void>((_, reject) => (fail = reject));
    player.toggle("c1", "u1");
    playImpl = async () => undefined;
    player.toggle("c2", "u2");
    fail(new Error("AbortError"));
    await Promise.resolve();
    await Promise.resolve();
    expect(player.currentId.value).toBe("c2");
    expect(player.playing.value).toBe(true);
    expect(toast.toasts.value).toHaveLength(0);
  });

  it("toasts when the element reports a media error", async () => {
    const { player, toast } = await load();
    player.toggle("c1", "u1");
    player.element().dispatchEvent(new Event("error"));
    expect(player.currentId.value).toBeNull();
    expect(toast.toasts.value.at(-1)?.kind).toBe("error");
  });
});
