/**
 * Per-device identifier. A refresh token is bound to it (ARCHITECTURE.md §9), which is
 * also what lets the server lock exactly this device into child mode.
 */

const KEY = 'bruno.device_id';

function generate(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** Held in memory too, so a blocked localStorage cannot hand out a new id per call. */
let cached: string | null = null;

export function deviceId(): string {
  if (typeof window === 'undefined') return 'server';
  if (cached !== null) return cached;
  try {
    const existing = window.localStorage.getItem(KEY);
    if (existing) {
      cached = existing;
      return existing;
    }
    const created = generate();
    window.localStorage.setItem(KEY, created);
    cached = created;
    return created;
  } catch {
    // private mode or storage blocked: one id for as long as the page lives, rather than
    // a different "device" on every call
    cached = generate();
    return cached;
  }
}
