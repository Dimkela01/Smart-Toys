'use client';

/**
 * Keeps a child screen locked (F-04, UC-05 AC).
 *
 * The browser back button, URL changes and parent routes must not get out of child mode;
 * only the hidden corner gesture plus the PIN does (UC-21). The real lock is on the server
 * (child_mode_at on the device's refresh token); this hook only stops the browser from
 * wandering off, so the child never lands on a parent screen.
 */

import { useEffect } from 'react';

export function useLockedScreen(): void {
  useEffect(() => {
    // one extra history entry to swallow, re-armed every time back is pressed
    window.history.pushState({ childMode: true }, '');
    const onPopState = () => {
      window.history.pushState({ childMode: true }, '');
    };
    const onContextMenu = (event: Event) => event.preventDefault();
    const onKeyDown = (event: KeyboardEvent) => {
      // nothing to select, copy, print or reload by keyboard on a toy screen
      if ((event.ctrlKey || event.metaKey) && ['p', 's', 'r', 'f'].includes(event.key)) {
        event.preventDefault();
      }
    };

    window.addEventListener('popstate', onPopState);
    window.addEventListener('contextmenu', onContextMenu);
    window.addEventListener('keydown', onKeyDown);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      window.removeEventListener('popstate', onPopState);
      window.removeEventListener('contextmenu', onContextMenu);
      window.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, []);
}
