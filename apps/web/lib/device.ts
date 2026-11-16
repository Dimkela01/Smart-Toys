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

export function deviceId(): string {
  if (typeof window === 'undefined') return 'server';
  try {
    const existing = window.localStorage.getItem(KEY);
    if (existing) return existing;
    const created = generate();
    window.localStorage.setItem(KEY, created);
    return created;
  } catch {
    // private mode or storage blocked: a per-tab id still works for one session
    return generate();
  }
}
