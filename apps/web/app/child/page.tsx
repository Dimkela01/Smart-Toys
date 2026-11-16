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
import {
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
import { useLockedScreen } from '@/lib/useLockedScreen';

export default function ChildPickerPage(): ReactNode {
  const router = useRouter();
  const [children, setChildren] = useState<ChildPicker[] | null>(null);
  const [labels, setLabels] = useState<Record<string, AvatarEntry>>({});
  const [busy, setBusy] = useState(false);

  useLockedScreen();

  const leave = useCallback(() => {
    clearChildMode();
    router.replace('/');
  }, [router]);

  useEffect(() => {
    if (!childModeToken()) {
      leave();
      return;
    }
    const pictures = storedPictures();
    if (pictures === null || pictures.length === 0) {
      leave();
      return;
    }
    setChildren(pictures);
  }, [leave]);

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
