'use client';

/**
 * Placeholder toy screen (F-05 groundwork, UI.md §3.2).
 *
 * M1 shows the character with its seven states, the paw, the activity cards and the hidden
 * exit. There is no voice yet: pressing the paw moves the character between listening and
 * idle locally. M2 adds the audio capture, the WebSocket and the real turn pipeline.
 *
 * Nothing on this screen is text for the child (docs/CLAUDE.md §2): the only words belong
 * to the parent PIN pad.
 */

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Character, type CharacterState } from '@/components/Character';
import { PawButton } from '@/components/PawButton';
import { PinPad } from '@/components/PinPad';
import { ApiError, request, type ChildToy } from '@/lib/api';
import { childSessionToken, clearChildMode, storedChild } from '@/lib/childSession';
import { LocaleProvider, translate, type Locale } from '@/lib/i18n';
import { useLockedScreen } from '@/lib/useLockedScreen';
import { useSession } from '@/lib/session';

const EXIT_HOLD_MS = 3000;

const ACTIVITY_ICONS: Record<string, ReactNode> = {
  why: (
    <svg viewBox="0 0 48 48" aria-hidden="true" className="h-8 w-8">
      <path
        d="M18 18a6 6 0 1 1 8 5.7V28"
        fill="none"
        stroke="#2b2b2b"
        strokeWidth="4"
        strokeLinecap="round"
      />
      <circle cx="24" cy="36" r="2.6" fill="#2b2b2b" />
    </svg>
  ),
  story: (
    <svg viewBox="0 0 48 48" aria-hidden="true" className="h-8 w-8">
      <path
        d="M8 12h14a4 4 0 0 1 4 4v20a4 4 0 0 0-4-4H8Zm32 0H26a4 4 0 0 0-4 4v20a4 4 0 0 1 4-4h14Z"
        fill="none"
        stroke="#2b2b2b"
        strokeWidth="3.5"
        strokeLinejoin="round"
      />
    </svg>
  ),
  // apples, as in UI.md §3.2
  numbers: (
    <svg viewBox="0 0 48 48" aria-hidden="true" className="h-8 w-8">
      <g fill="#c0392b">
        <circle cx="15" cy="21" r="8" />
        <circle cx="33" cy="21" r="8" />
        <circle cx="24" cy="35" r="8" />
      </g>
      <g stroke="#4b7a3a" strokeWidth="2.5" strokeLinecap="round">
        <path d="M15 13v-3" />
        <path d="M33 13v-3" />
        <path d="M24 27v-3" />
      </g>
    </svg>
  ),
  // ABC flag, as in UI.md §3.2
  english: (
    <svg viewBox="0 0 48 48" aria-hidden="true" className="h-8 w-8">
      <path d="M11 9v30" stroke="#2b2b2b" strokeWidth="3" strokeLinecap="round" />
      <path d="M13 11h26v16H13z" fill="#5C8AE6" />
      <text x="26" y="23" textAnchor="middle" fontSize="11" fontWeight="700" fill="#fff">
        ABC
      </text>
    </svg>
  ),
};

/** Fixed order, so the cards do not move about between children (UI.md §3.2). */
const ACTIVITY_ORDER = ['why', 'story', 'numbers', 'english'] as const;

export default function ToyScreen(): ReactNode {
  const router = useRouter();
  const { refresh } = useSession();
  const [child, setChild] = useState<ChildToy | null>(null);
  const [state, setState] = useState<CharacterState>('sleeping');
  const [pinOpen, setPinOpen] = useState(false);
  const [pinError, setPinError] = useState<string | undefined>();
  const [pinBusy, setPinBusy] = useState(false);
  const holdTimer = useRef<number | null>(null);

  useLockedScreen();

  const locale: Locale = child?.language ?? 'sr';
  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => translate(locale, key, vars),
    [locale],
  );

  const leave = useCallback(() => {
    clearChildMode();
    router.replace('/child');
  }, [router]);

  useEffect(() => {
    const stored = storedChild();
    if (!stored || !childSessionToken()) {
      leave();
      return;
    }
    setChild(stored);
    // Bruno wakes up when the child arrives (UC-05 step 4)
    const wake = window.setTimeout(() => setState('idle'), 400);
    return () => window.clearTimeout(wake);
  }, [leave]);

  function startExitHold(): void {
    if (holdTimer.current !== null) return;
    holdTimer.current = window.setTimeout(() => {
      holdTimer.current = null;
      setPinError(undefined);
      setPinOpen(true);
    }, EXIT_HOLD_MS);
  }

  function cancelExitHold(): void {
    if (holdTimer.current !== null) {
      window.clearTimeout(holdTimer.current);
      holdTimer.current = null;
    }
  }

  async function submitPin(pin: string): Promise<void> {
    const token = childSessionToken();
    if (!token) {
      leave();
      return;
    }
    setPinBusy(true);
    setPinError(undefined);
    try {
      await request('/child-mode/exit', { method: 'POST', body: { pin }, token });
      clearChildMode();
      // the parent session comes back only after the PIN (UC-21)
      await refresh();
      router.replace('/dashboard');
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'pin_locked') {
        setPinError(t('child.exitLocked'));
      } else if (caught instanceof ApiError && caught.code === 'invalid_pin') {
        setPinError(t('child.exitWrong'));
      } else if (caught instanceof ApiError && caught.code === 'child_mode_inactive') {
        leave();
      } else {
        setPinError(t('common.errorGeneric'));
      }
    } finally {
      setPinBusy(false);
    }
  }

  if (child === null) return <div className="child-screen" />;

  // disabled activities are hidden, not greyed out (UI.md §3.2)
  const activities = ACTIVITY_ORDER.filter((key) => child.activities_enabled[key]);

  return (
    <LocaleProvider locale={locale}>
      <div className="child-screen flex flex-col items-center justify-between py-4">
        {/* hidden exit for parents: 3-second press, top-left corner (UC-21) */}
        <button
          type="button"
          aria-label={t('child.exitLabel')}
          onPointerDown={startExitHold}
          onPointerUp={cancelExitHold}
          onPointerLeave={cancelExitHold}
          onPointerCancel={cancelExitHold}
          className="absolute top-0 left-0 h-16 w-16 opacity-0"
        />

        <div className="flex flex-1 items-center justify-center">
          <Character characterId={child.character_id} state={state} label={child.nickname} />
        </div>

        <div className="flex items-center justify-center gap-3" role="group">
          {activities.map((activity) => (
            <button
              key={activity}
              type="button"
              aria-label={t(
                `child.activity${activity.charAt(0).toUpperCase()}${activity.slice(1)}`,
              )}
              onClick={() => setState('happy')}
              className="grid h-16 w-16 place-items-center rounded-2xl bg-white/80"
            >
              {ACTIVITY_ICONS[activity] ?? null}
            </button>
          ))}
        </div>

        <div className="pt-4 pb-2">
          <PawButton
            label={t('child.pawLabel')}
            onPressStart={() => setState('listening')}
            onPressEnd={() => setState('idle')}
          />
        </div>

        {pinOpen ? (
          <PinPad
            title={t('child.exitTitle')}
            cancelLabel={t('common.cancel')}
            error={pinError}
            busy={pinBusy}
            onSubmit={(pin) => void submitPin(pin)}
            onCancel={() => setPinOpen(false)}
          />
        ) : null}
      </div>
    </LocaleProvider>
  );
}
