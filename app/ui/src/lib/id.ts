let seq = 0;

/** Unique id with a readable prefix. crypto.randomUUID is absent on plain-HTTP origins, so fall back to a counter. */
export function newId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return `${prefix}-${uuid}`;
  return `${prefix}-${++seq}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}
