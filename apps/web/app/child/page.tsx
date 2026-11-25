'use client';

/**
 * Picture picker (F-04, UC-05, UI.md §3.1).
 *
 * No reading required: pictures only, at least 120 px, with labels for screen readers.
 * The child taps their picture and the toy screen opens.
 *
 * Entering child mode is a parent action (/child-mode/enter needs a parent token), so the
 * dashboard does that and leaves the token and the pictures on the device. A reload here
 * therefore works without the parent session, which the lock refuses to hand back.
 */

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Avatar } from '@/components/Avatar';
import { PinPad } from '@/components/PinPad';
import {
  ApiError,
  catalog,
  request,
  type Avatar as AvatarEntry,
  type ChildPicker,
  type SelectChildResponse,
} from '@/lib/api';
import {
  childModeToken,
  clearChildMode,
  setChildSession,
  storedPictures,
} from '@/lib/childSession';
import { useT } from '@/lib/i18n';
import { useLockedScreen } from '@/lib/useLockedScreen';
import { useSession } from '@/lib/session';

export default function ChildPickerPage(): ReactNode {
  const router = useRouter();
  const t = useT();
  const { refresh } = useSession();
  const [children, setChildren] = useState<ChildPicker[] | null>(null);
  const [labels, setLabels] = useState<Record<string, AvatarEntry>>({});
  const [busy, setBusy] = useState(false);
  /**
   * A second tab, a reopened browser or a restored session has its own (empty)
   * sessionStorage, so it holds no child-mode token even though the device is still locked
   * on the server. Such a tab must explain itself and offer the PIN:
   *
   * - redirecting back to the landing page sent the two screens into an endless loop,
   *   which iOS Safari turns into "a client-side exception has occurred";
   * - explaining alone was a dead end, because /child-mode/exit needs the very token this
   *   tab is missing, so the parent could never get their account back on this device.
   *
   * /auth/unlock takes the PIN with the refresh cookie instead (UC-21).
   */
  const [locked, setLocked] = useState(false);
  const [pinOpen, setPinOpen] = useState(false);
  const [pinError, setPinError] = useState<string | undefined>();
  const [pinBusy, setPinBusy] = useState(false);

  useLockedScreen();

  const leave = useCallback(() => {
    clearChildMode();
    router.replace('/');
  }, [router]);

  useEffect(() => {
    const pictures = storedPictures();
    if (!childModeToken() || pictures === null || pictures.length === 0) {
      setLocked(true);
      return;
    }
    setChildren(pictures);
  }, []);

  // the catalog is only needed for the screen-reader labels
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const loaded = await catalog();
        if (!cancelled) {
          setLabels(Object.fromEntries(loaded.avatars.map((avatar) => [avatar.id, avatar])));
        }
      } catch {
        // labels are optional; the pictures still work
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function pick(child: ChildPicker): Promise<void> {
    const token = childModeToken();
    if (!token || busy) return;
    setBusy(true);
    try {
      const selected = await request<SelectChildResponse>('/child-mode/select', {
        method: 'POST',
        body: { child_id: child.id },
        token,
      });
      setChildSession(selected.token, selected.child);
      router.replace('/child/toy');
    } catch {
      // the parent ended child mode, or the token expired
      setBusy(false);
      leave();
    }
  }

  async function unlock(pin: string): Promise<void> {
    setPinBusy(true);
    setPinError(undefined);
    try {
      await request('/auth/unlock', { method: 'POST', body: { pin } });
      clearChildMode();
      // the parent session comes back only after the PIN (UC-21)
      await refresh();
      router.replace('/dashboard');
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'pin_locked') {
        setPinError(t('child.exitLocked'));
      } else if (caught instanceof ApiError && caught.code === 'invalid_pin') {
        setPinError(t('child.exitWrong'));
      } else if (caught instanceof ApiError && caught.status === 401) {
        // the device was signed out elsewhere: there is nothing left to unlock
        setPinOpen(false);
        router.replace('/login');
      } else {
        setPinError(t('common.errorGeneric'));
      }
    } finally {
      setPinBusy(false);
    }
  }

  if (locked) {
    return (
      <div className="child-screen grid place-items-center p-6">
        <div className="max-w-xs rounded-2xl bg-white/90 p-5 text-center">
          <h1 className="text-lg font-semibold">{t('child.lockedTitle')}</h1>
          <p className="mt-2 text-sm text-[var(--color-parent-muted)]">{t('child.lockedText')}</p>
          {/* behind a button, so a child poking at the screen cannot spend the five
              attempts that lock the PIN for five minutes */}
          <button
            type="button"
            onClick={() => {
              setPinError(undefined);
              setPinOpen(true);
            }}
            className="mt-4 min-h-12 w-full rounded-xl bg-[var(--color-parent-accent)] px-4 text-sm font-medium text-[var(--color-parent-accent-ink)]"
          >
            {t('child.unlockButton')}
          </button>
        </div>

        {pinOpen ? (
          <PinPad
            title={t('child.exitTitle')}
            cancelLabel={t('common.cancel')}
            error={pinError}
            busy={pinBusy}
            onSubmit={(pin) => void unlock(pin)}
            onCancel={() => setPinOpen(false)}
          />
        ) : null}
      </div>
    );
  }

  return (
    <div className="child-screen grid place-items-center p-5">
      <div className="flex max-w-md flex-wrap justify-center gap-5">
        {children?.map((child) => (
          <button
            key={child.id}
            type="button"
            disabled={busy}
            onClick={() => void pick(child)}
            aria-label={child.nickname}
            className="rounded-3xl bg-white/70 p-2 disabled:opacity-60"
          >
            <Avatar
              avatarId={child.avatar_id}
              label={labels[child.avatar_id]?.label.en ?? child.nickname}
              size={132}
            />
          </button>
        ))}
      </div>
    </div>
  );
}
