const clamp = (n: number, max: number) =>
  Math.min(Math.max(0, n), Math.max(0, max));
export function timeToX(t: number, duration: number, width: number): number {
  return duration > 0 && width > 0
    ? (clamp(t, duration) / duration) * width
    : 0;
}
export function xToTime(x: number, duration: number, width: number): number {
  return width > 0 && duration > 0 ? (clamp(x, width) / width) * duration : 0;
}
export function snapTime(t: number, fps: number | null): number {
  const grid = fps && fps > 0 ? fps : 100;
  return Math.round(t * grid) / grid;
}
export function frameIndexForTime(
  t: number,
  interval: number,
  count: number,
): number {
  return interval > 0 ? clamp(Math.floor(t / interval), count - 1) : 0;
}
