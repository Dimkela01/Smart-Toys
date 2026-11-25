'use client';

/**
 * The toy screen (F-05, UI.md §3.2).
 *
 * Hold the paw, speak, and Bruno answers by voice. The character's state comes from the
 * server while a turn is running (UI.md §3.3) and its mouth from the audio actually
 * playing; the ring around the paw comes from the microphone. Everything to do with
 * audio lives in lib/audio - see useVoice.
 *
 * Nothing on this screen is text for the child (docs/CLAUDE.md §2): the only words
 * belong to the parent PIN pad. A failure is heard, never shown (NFR-09, UC-22).
 */

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Character, type CharacterState } from '@/components/Character';
import { PawButton } from '@/components/PawButton';
import { PinPad } from '@/components/PinPad';
import { ApiError, request, type ChildToy } from '@/lib/api';
import { useVoice } from '@/lib/audio/useVoice';
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
  const [token, setToken] = useState<string | null>(null);
  /** Set only by a tapped activity card; the voice loop owns every other state. */
  const [celebrating, setCelebrating] = useState(false);
  const [pinOpen, setPinOpen] = useState(false);
  const [pinError, setPinError] = useState<string | undefined>();
  const [pinBusy, setPinBusy] = useState(false);
  const holdTimer = useRef<number | null>(null);
  const celebrationTimer = useRef<number | null>(null);

  useLockedScreen();

  const locale: Locale = child?.language ?? 'sr';
  const voice = useVoice(token, locale);
  const state: CharacterState = celebrating ? 'happy' : voice.state;
  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => translate(locale, key, vars),
    [locale],
  );

  const leave = useCallback(() => {
    clearChildMode();
    router.replace('/child');
  }, [router]);

  const stopCelebrating = useCallback(() => {
    if (celebrationTimer.current !== null) {
      window.clearTimeout(celebrationTimer.current);
      celebrationTimer.current = null;
    }
    setCelebrating(false);
  }, []);

  /**
   * Tapping an activity card is acknowledged, then Bruno settles back down. The activity
   * engine itself is M4, so for now the card only says "I saw that".
   */
  const celebrate = useCallback(() => {
    if (celebrationTimer.current !== null) window.clearTimeout(celebrationTimer.current);
    setCelebrating(true);
    celebrationTimer.current = window.setTimeout(() => {
      celebrationTimer.current = null;
      setCelebrating(false);
    }, 1200);
  }, []);

  useEffect(() => {
    const stored = storedChild();
    const session = childSessionToken();
    if (!stored || !session) {
      leave();
      return;
    }
    setChild(stored);
    setToken(session);
    return () => {
      stopCelebrating();
    };
  }, [leave, stopCelebrating]);

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

        {/* min-h-0 lets this shrink; without it the character keeps its height and the
            paw is pushed outside the fixed, non-scrolling screen in landscape */}
        <div className="flex w-full min-h-0 flex-1 items-center justify-center px-4">
          <Character
            characterId={child.character_id}
            state={state}
            label={child.nickname}
            mouth={voice.mouth}
          />
        </div>

        <div className="flex items-center justify-center gap-3" role="group">
          {activities.map((activity) => (
            <button
              key={activity}
              type="button"
              aria-label={t(
                `child.activity${activity.charAt(0).toUpperCase()}${activity.slice(1)}`,
              )}
              onClick={celebrate}
              className="grid h-16 w-16 place-items-center rounded-2xl bg-white/80"
            >
              {ACTIVITY_ICONS[activity] ?? null}
            </button>
          ))}
        </div>

        <div className="pt-4 pb-4">
          <PawButton
            label={t('child.pawLabel')}
            level={voice.inputLevel}
            // the microphone needs a secure context, so a device on plain http can see
            // the paw but cannot record with it (make https)
            disabled={!voice.possible || !voice.connected}
            // the paw wins over a celebration still in progress
            onPressStart={() => {
              stopCelebrating();
              voice.pressDown();
            }}
            onPressEnd={voice.pressUp}
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
