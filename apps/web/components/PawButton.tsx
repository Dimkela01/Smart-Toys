'use client';

/**
 * Hold-to-talk paw (UI.md §3.2): at least 96 px, press and hold, release to send, and the
 * space bar does the same on a desktop.
 *
 * `level` is the microphone RMS while the paw is held: it draws the ring around the paw
 * (§6.1), which is the only feedback a child gets that they are being heard.
 */

import { useCallback, useEffect, useRef, type ReactNode } from 'react';

export function PawButton({
  label,
  onPressStart,
  onPressEnd,
  disabled = false,
  level = 0,
}: {
  label: string;
  onPressStart: () => void;
  onPressEnd: () => void;
  disabled?: boolean;
  /** Microphone RMS, 0 to about 0.3 in ordinary speech. */
  level?: number;
}): ReactNode {
  const held = useRef(false);

  const start = useCallback(() => {
    if (disabled || held.current) return;
    held.current = true;
    if ('vibrate' in navigator) navigator.vibrate?.(12);
    onPressStart();
  }, [disabled, onPressStart]);

  const end = useCallback(() => {
    if (!held.current) return;
    held.current = false;
    onPressEnd();
  }, [onPressEnd]);

  useEffect(() => {
    const down = (event: KeyboardEvent) => {
      if (event.code === 'Space' && !event.repeat) {
        event.preventDefault();
        start();
      }
    };
    const up = (event: KeyboardEvent) => {
      if (event.code === 'Space') {
        event.preventDefault();
        end();
      }
    };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
    };
  }, [start, end]);

  // RMS is small and uneven, so it is scaled and clamped into a ring that reacts
  // visibly to a quiet child without flapping at a loud one
  const ring = Math.min(1, level * 6);

  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      style={{ ['--ring' as string]: ring.toFixed(3) }}
      onPointerDown={start}
      onPointerUp={end}
      onPointerCancel={end}
      onPointerLeave={end}
      onContextMenu={(event) => event.preventDefault()}
      className="paw"
    >
      <svg viewBox="0 0 120 120" aria-hidden="true" className="h-3/5 w-3/5">
        <circle cx="60" cy="72" r="30" fill="#fff" opacity="0.92" />
        <circle cx="34" cy="42" r="12" fill="#fff" opacity="0.92" />
        <circle cx="54" cy="32" r="12" fill="#fff" opacity="0.92" />
        <circle cx="76" cy="34" r="12" fill="#fff" opacity="0.92" />
        <circle cx="94" cy="48" r="11" fill="#fff" opacity="0.92" />
      </svg>

      <style jsx>{`
        .paw {
          position: relative;
          width: 112px;
          height: 112px;
          min-width: 96px;
          min-height: 96px;
          border: none;
          border-radius: 9999px;
          background: var(--color-paw);
          box-shadow: 0 6px 0 rgba(0, 0, 0, 0.18);
          display: grid;
          place-items: center;
          touch-action: none;
          transition: transform 0.08s ease;
        }
        /* grows with the child's voice; transform only, so it never costs a layout */
        .paw::before {
          content: '';
          position: absolute;
          inset: -14px;
          border-radius: 9999px;
          border: 4px solid var(--color-paw);
          opacity: calc(0.25 + var(--ring, 0) * 0.75);
          transform: scale(calc(1 + var(--ring, 0) * 0.18));
          transition:
            transform 0.08s linear,
            opacity 0.08s linear;
          pointer-events: none;
        }
        .paw:active {
          transform: translateY(4px) scale(0.98);
          box-shadow: 0 2px 0 rgba(0, 0, 0, 0.18);
        }
        .paw:disabled {
          filter: grayscale(0.6);
          opacity: 0.6;
        }
      `}</style>
    </button>
  );
}
