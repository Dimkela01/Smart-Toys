/**
 * Child-mode tokens on the device.
 *
 * Kept in sessionStorage so that a reload (or a child closing and reopening the tab)
 * does not strand the child on a dead screen: the parent session cannot be refreshed
 * while the device is locked, so there would be no way back to the toy screen.
 *
 * The token is useless once the parent exits child mode or signs out: the server stops
 * accepting it immediately (403 child_mode_inactive). Not specified in the docs; listed
 * in the M1 report.
 */

import type { ChildPicker, ChildToy } from '@/lib/api';

const MODE_KEY = 'bruno.child_mode_token';
const SESSION_KEY = 'bruno.child_session_token';
const CHILD_KEY = 'bruno.child';
const PICKER_KEY = 'bruno.child_pictures';

function read(key: string): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  if (typeof window === 'undefined') return;
  try {
    if (value === null) window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, value);
  } catch {
    // private mode: child mode then lasts only as long as the page stays open
  }
}

export const childModeToken = () => read(MODE_KEY);
export const childSessionToken = () => read(SESSION_KEY);

/**
 * Entering child mode is a parent action, so only the dashboard can call
 * /child-mode/enter. The pictures it returns are kept here, so a reload of the picker
 * does not need the parent session back (which the lock deliberately refuses).
 */
export function setChildMode(token: string, pictures: ChildPicker[]): void {
  write(MODE_KEY, token);
  write(PICKER_KEY, JSON.stringify(pictures));
}

export function storedPictures(): ChildPicker[] | null {
  const raw = read(PICKER_KEY);
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ChildPicker[]) : null;
  } catch {
    return null;
  }
}

export function setChildSession(token: string, child: ChildToy): void {
  write(SESSION_KEY, token);
  write(CHILD_KEY, JSON.stringify(child));
}

export function storedChild(): ChildToy | null {
  const raw = read(CHILD_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as ChildToy;
  } catch {
    return null;
  }
}

export function clearChildMode(): void {
  write(MODE_KEY, null);
  write(SESSION_KEY, null);
  write(CHILD_KEY, null);
  write(PICKER_KEY, null);
}
