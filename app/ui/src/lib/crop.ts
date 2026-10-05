export type Rect = { x: number; y: number; w: number; h: number };
const even = (n: number) => Math.round(n / 2) * 2;
export function clampCrop(r: Rect, srcW: number, srcH: number, min = 64): Rect {
  const maxW = Math.floor(srcW / 2) * 2,
    maxH = Math.floor(srcH / 2) * 2;
  const w = Math.min(maxW, Math.max(even(min), even(r.w)));
  const h = Math.min(maxH, Math.max(even(min), even(r.h)));
  return {
    x: Math.max(0, Math.min(maxW - w, even(r.x))),
    y: Math.max(0, Math.min(maxH - h, even(r.y))),
    w,
    h,
  };
}
export function cropFromDisplay(
  r: Rect,
  displayW: number,
  displayH: number,
  srcW: number,
  srcH: number,
): Rect {
  if (displayW <= 0 || displayH <= 0)
    return clampCrop({ x: 0, y: 0, w: srcW, h: srcH }, srcW, srcH);
  return clampCrop(
    {
      x: (r.x * srcW) / displayW,
      y: (r.y * srcH) / displayH,
      w: (r.w * srcW) / displayW,
      h: (r.h * srcH) / displayH,
    },
    srcW,
    srcH,
  );
}
export function displayFromCrop(
  r: Rect,
  displayW: number,
  displayH: number,
  srcW: number,
  srcH: number,
): Rect {
  return {
    x: (r.x * displayW) / srcW,
    y: (r.y * displayH) / srcH,
    w: (r.w * displayW) / srcW,
    h: (r.h * displayH) / srcH,
  };
}
/** Anchor names identify the moving handle; the opposite corner stays fixed. */
export function aspectLock(
  r: Rect,
  aspect: number,
  anchor: "nw" | "ne" | "sw" | "se",
): Rect {
  if (!(aspect > 0)) return { ...r };
  const h = r.w / aspect;
  return { ...r, y: anchor.startsWith("n") ? r.y + r.h - h : r.y, h };
}
